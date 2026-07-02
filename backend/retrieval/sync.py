import asyncio
import logging
import httpx
from datetime import datetime, timezone
from sqlalchemy.future import select

from backend.db.base import AsyncSessionLocal
from backend.db.models import IndexedRepo, User
from backend.db import crud
from backend.security.encryption import decrypt_token
from backend.retrieval.indexing import index_repository_pipeline

logger = logging.getLogger("loom.retrieval.sync")

async def start_auto_sync_loop():
    """
    Background loop that checks for updates on GitHub for all indexed repositories.
    Runs every 5 minutes.
    """
    logger.info("Starting background repository auto-sync service...")
    await asyncio.sleep(10)  # Wait for application startup to complete
    
    while True:
        try:
            logger.info("Checking indexed repositories for updates on GitHub...")
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(IndexedRepo).filter(
                        IndexedRepo.status == "ready"
                    )
                )
                repos = result.scalars().all()
                
                for repo in repos:
                    user = await crud.get_user_by_id(db, repo.user_id)
                    if not user:
                        continue
                    
                    try:
                        access_token = decrypt_token(user.access_token_encrypted)
                    except Exception as dec_err:
                        logger.error(f"Failed to decrypt token for user {user.github_username}: {dec_err}")
                        continue
                    
                    # Fetch latest commit from GitHub
                    headers = {
                        "Authorization": f"token {access_token}",
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "Loom"
                    }
                    url = f"https://api.github.com/repos/{repo.repo_full_name}/commits"
                    
                    try:
                        async with httpx.AsyncClient() as client:
                            res = await client.get(url, headers=headers, params={"per_page": 1}, timeout=10.0)
                            if res.status_code == 200:
                                commits = res.json()
                                if commits and len(commits) > 0:
                                    latest_sha = commits[0]["sha"]
                                    if latest_sha != repo.last_commit_sha:
                                        logger.info(
                                            f"Detected update for {repo.repo_full_name}. "
                                            f"Local SHA: {repo.last_commit_sha}, Remote SHA: {latest_sha}. "
                                            f"Triggering auto-reindexing..."
                                        )
                                        # Set status to indexing
                                        await crud.update_repo_status(db, repo.id, "indexing")
                                        
                                        # Start indexing task asynchronously
                                        asyncio.create_task(
                                            index_repository_pipeline(
                                                user.id,
                                                repo.id,
                                                repo.repo_full_name,
                                                access_token,
                                                repo.vector_collection_name
                                            )
                                        )
                            elif res.status_code == 404:
                                logger.warning(f"Repository {repo.repo_full_name} not found or no access.")
                            else:
                                logger.error(f"GitHub API returned status {res.status_code} for {repo.repo_full_name}: {res.text}")
                    except Exception as api_err:
                        logger.error(f"Error checking updates for {repo.repo_full_name}: {api_err}")
                        
        except Exception as loop_err:
            logger.exception(f"Unexpected error in auto-sync loop: {loop_err}")
            
        # Poll every 5 minutes (300 seconds)
        await asyncio.sleep(300)
