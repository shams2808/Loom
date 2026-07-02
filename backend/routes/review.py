import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.base import get_db
from backend.db.models import User
from backend.auth.dependencies import get_current_user
from backend.orchestrators.review_orchestrator import (
    ReviewRequest,
    ReviewResponse,
    generate_pr_review,
    LLMServiceError
)

logger = logging.getLogger("loom.routes.review")

router = APIRouter(tags=["review"])

@router.post("/review", response_model=ReviewResponse)
async def review(
    request: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Triggers code review for a PR diff.
    Conforms to PRD Section 5.4 contract.
    """
    try:
        if not request.diff:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="diff is required"
            )

        return await generate_pr_review(request, current_user, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Request: {str(e)}"
        )
    except LLMServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM call failed"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception(f"Unexpected error in /review route: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
