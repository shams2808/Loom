import logging
import httpx
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.base import get_db
from backend.db import crud
from backend.db.models import User
from backend.auth.dependencies import get_current_user
from backend.security.encryption import decrypt_token
from backend.retrieval.indexing import index_repository_pipeline
from backend.session.indexing_status import indexing_jobs, IndexingProgress

logger = logging.getLogger("loom.routes.repos")

router = APIRouter(tags=["repos"])

class IndexRequest(BaseModel):
    repo_full_name: str = Field(..., description="GitHub repository full name (owner/repo)")

@router.get("/repos/github")
async def get_github_repos(current_user: User = Depends(get_current_user)):
    """
    Retrieves the user's personal repositories live from the GitHub API.
    Conforms to PRD Section 5.2.
    """
    try:
        access_token = decrypt_token(current_user.access_token_encrypted)
    except Exception as e:
        logger.error(f"Failed to decrypt token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt authentication credentials."
        )

    # Fetch repositories owned, collaborated, or member of organizations
    url = "https://api.github.com/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator,organization_member"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Loom-Backend/1.0"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            repos_data = resp.json()
        except Exception as e:
            logger.exception(f"Failed to fetch repositories from GitHub: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub API connection failed: {str(e)}"
            )

    repos = []
    for r in repos_data:
        repos.append({
            "full_name": r.get("full_name"),
            "private": r.get("private"),
            "default_branch": r.get("default_branch", "main")
        })
    return {"repos": repos}

@router.post("/repos/index")
async def index_repository(
    payload: IndexRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Triggers indexing for a repository. Creates an IndexedRepo entry in DB
    and spawns a background indexing task.
    Conforms to PRD Section 5.2.
    """
    repo_full_name = payload.repo_full_name.strip()
    if not repo_full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="repo_full_name is required"
        )
    
    try:
        access_token = decrypt_token(current_user.access_token_encrypted)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt token."
        )

    # 1. Fetch live repository details to verify permissions and get github_repo_id
    verify_url = f"https://api.github.com/repos/{repo_full_name}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Loom-Backend/1.0"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(verify_url, headers=headers)
            if resp.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository '{repo_full_name}' not found or not accessible on GitHub."
                )
            resp.raise_for_status()
            repo_meta = resp.json()
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Failed to verify repository details from GitHub: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not connect to GitHub to verify repository: {str(e)}"
            )

    github_repo_id = repo_meta.get("id")
    if not github_repo_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve GitHub repository ID."
        )

    # 2. Check if already indexing/indexed
    repo = await crud.get_indexed_repo(db, current_user.id, github_repo_id)

    if repo:
        if repo.status == "indexing" and str(repo.id) in indexing_jobs:
            return {"repo_id": str(repo.id), "status": "indexing"}
        # Reset back to indexing
        repo.status = "indexing"
        repo.repo_full_name = repo_full_name
        await db.commit()
        await db.refresh(repo)
    else:
        # Create a user-scoped collection name to isolate data
        clean_user_id = str(current_user.id).replace("-", "_")
        vector_collection_name = f"user_{clean_user_id}_repo_{github_repo_id}"
        
        repo = await crud.create_indexed_repo(
            db=db,
            user_id=current_user.id,
            github_repo_id=github_repo_id,
            repo_full_name=repo_full_name,
            vector_collection_name=vector_collection_name,
            status="indexing"
        )
    
    repo_id_str = str(repo.id)
    indexing_jobs[repo_id_str] = IndexingProgress(
        repo_id=repo_id_str,
        repo_full_name=repo_full_name,
        status="indexing",
        current_batch=0,
        total_batches=0,
        files_processed=0,
        total_chunks=0
    )

    # 3. Add to background tasks
    background_tasks.add_task(
        index_repository_pipeline,
        current_user.id,
        repo.id,
        repo_full_name,
        access_token,
        repo.vector_collection_name
    )

    return {"repo_id": repo_id_str, "status": "indexing"}

@router.get("/repos/indexed")
async def get_indexed_repositories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns the list of repositories indexed by the current user.
    Conforms to PRD Section 5.2.
    """
    repos = await crud.get_indexed_repos_by_user(db, current_user.id)
    
    return {
        "repos": [
            {
                "repo_id": str(r.id),
                "repo_full_name": r.repo_full_name,
                "status": r.status,
                "chunk_count": r.chunk_count,
                "last_indexed_at": r.last_indexed_at.isoformat() if r.last_indexed_at else None
            }
            for r in repos
        ]
    }

@router.get("/repos/status/{repo_id}")
async def get_repo_status(
    repo_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns the indexing status of a repository.
    Conforms to PRD Section 5.2.
    """
    try:
        repo_uuid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid repository ID format."
        )

    repo = await crud.get_indexed_repo_by_id(db, current_user.id, repo_uuid)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found or not owned by current user."
        )

    # Check live memory state first for active jobs
    in_memory = indexing_jobs.get(repo_id)
    if in_memory and repo.status == "indexing":
        return {
            "status": in_memory.status,
            "chunk_count": in_memory.total_chunks,
            "current_batch": in_memory.current_batch,
            "total_batches": in_memory.total_batches,
            "files_processed": in_memory.files_processed,
            "last_indexed_at": repo.last_indexed_at.isoformat() if repo.last_indexed_at else None
        }

    return {
        "status": repo.status,
        "chunk_count": repo.chunk_count,
        "current_batch": repo.chunk_count,
        "total_batches": repo.chunk_count,
        "files_processed": 0,
        "last_indexed_at": repo.last_indexed_at.isoformat() if repo.last_indexed_at else None
    }
