import uuid
import logging
from typing import Optional, List
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db import crud
from backend.db.models import User
from backend.retrieval.interface import retrieve_context, ContextChunk
from backend.llm.client import LLMClient
from backend.llm.parsing import validate_and_parse, LLMParsingError
from backend.prompts.review_prompts import (
    build_file_review_system_prompt,
    build_file_review_user_prompt,
    build_summary_system_prompt,
    build_summary_user_prompt
)

logger = logging.getLogger("loom.orchestrator.review")

# Pydantic Schemas
class DiffFile(BaseModel):
    file: str = Field(..., description="File path relative to repository root")
    patch: str = Field(..., description="Unified diff patch of the changes")
    status: str = Field(..., description="'modified' | 'added' | 'deleted'")

class ReviewRequest(BaseModel):
    repo_id: Optional[str] = Field(None, description="The database UUID of the repository, or null for basic review")
    pr_title: str = Field(..., description="The title of the Pull Request")
    pr_description: str = Field(..., description="The description/body of the Pull Request")
    diff: List[DiffFile] = Field(..., description="List of files modified in the PR")

class Comment(BaseModel):
    file: str = Field(..., description="File path relative to repository root")
    line: int = Field(..., description="1-indexed line number in the new file")
    severity: str = Field(..., description="'info' | 'warning' | 'critical'")
    text: str = Field(..., description="Constructive code review comment text")

class ReviewResponse(BaseModel):
    summary: str = Field(..., description="Top-level PR review summary in markdown nested list format")
    comments: List[Comment] = Field(..., description="List of inline comments to post")
    context_aware: bool = Field(..., description="True if repository context was used, False otherwise")

# Inner LLM schemas
class FileCommentSchema(BaseModel):
    line: int
    severity: str  # 'info' | 'warning' | 'critical'
    text: str

class FileReviewSchema(BaseModel):
    comments: List[FileCommentSchema]

class LLMServiceError(Exception):
    pass

async def generate_pr_review(
    request: ReviewRequest,
    current_user: User,
    db: AsyncSession
) -> ReviewResponse:
    """
    Executes a file-by-file code review pipeline and compiles a final summary.
    """
    repo_id = request.repo_id
    pr_title = request.pr_title
    pr_description = request.pr_description
    diff_files = request.diff

    if not diff_files:
        raise ValueError("Diff files list cannot be empty.")

    # Validate repo_id if provided
    repo = None
    if repo_id:
        try:
            repo_uuid = uuid.UUID(repo_id)
            repo = await crud.get_indexed_repo_by_id(db, current_user.id, repo_uuid)
            if not repo:
                logger.warning(f"Access denied or repo not found: User {current_user.github_username} tried to query repo {repo_id}")
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: You do not have permission to query this repository."
                )
        except ValueError:
            raise ValueError("Invalid repository ID format.")

    collected_comments: List[Comment] = []
    context_retrieved_any = False

    # 1. Per-file review loop
    if not settings.gemini_api_key:
        raise LLMServiceError("GEMINI_API_KEY is not configured on the server.")

    client = LLMClient(api_key=settings.gemini_api_key, model=settings.llm_model)

    for diff_file in diff_files:
        filename = diff_file.file
        patch = diff_file.patch
        status = diff_file.status

        # Skip files with empty patches or collapsed files
        if not patch or "COLLAPSED" in patch or "EMPTY" in patch:
            continue

        # Fetch context if repo is ready (Context-Aware Mode)
        context_chunks: List[ContextChunk] = []
        if repo and repo.status == "ready":
            try:
                context_chunks = await retrieve_context(
                    query=patch,
                    repo_id=str(repo.id),
                    user_id=str(current_user.id),
                    top_k=5,
                    include_callers=True
                )
                if context_chunks:
                    context_retrieved_any = True
            except Exception as context_err:
                logger.warning(f"Failed to retrieve context for file {filename}: {context_err}")

        # Review file
        try:
            system_prompt = build_file_review_system_prompt()
            user_prompt = build_file_review_user_prompt(filename, patch, status, context_chunks)
            
            raw_response = await client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3
            )

            # Validate and parse comments
            file_review = validate_and_parse(raw_response, FileReviewSchema)
            
            # Map inner comments to final Comment instances
            for c in file_review.comments:
                severity = c.severity.lower()
                if severity not in ("info", "warning", "critical"):
                    severity = "info"  # Fallback to info on schema mismatch
                collected_comments.append(Comment(
                    file=filename,
                    line=c.line,
                    severity=severity,
                    text=c.text
                ))
        except Exception as e:
            # PRD Section 8.4: "if one file fails: skip it, log warning, continue"
            logger.warning(f"Failed to generate review for file '{filename}': {e}")
            continue

    # 2. Final top-level summary generation
    try:
        summary_system = build_summary_system_prompt()
        summary_user = build_summary_user_prompt(pr_title, pr_description, [c.model_dump() for c in collected_comments])
        
        # Call LLM complete with response_mime_type="text/plain" so it returns markdown
        summary_markdown = await client.complete(
            system_prompt=summary_system,
            user_prompt=summary_user,
            max_tokens=2000,
            temperature=0.3,
            response_mime_type="text/plain"
        )
    except Exception as summary_err:
        logger.warning(f"Failed to generate top-level review summary: {summary_err}")
        # Construct a fallback summary
        summary_markdown = (
            f"* **Core Changes**:\n"
            f"  1. Review generated with {len(collected_comments)} inline comments.\n"
            f"* **Architectural Impact**:\n"
            f"  1. Summary generation failed due to an error: {str(summary_err)}.\n"
            f"* **Testing & Verification**:\n"
            f"  1. Please verify changes manually.\n"
        )

    context_aware = (repo is not None) and context_retrieved_any

    return ReviewResponse(
        summary=summary_markdown,
        comments=collected_comments,
        context_aware=context_aware
    )
