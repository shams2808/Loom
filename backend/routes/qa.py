import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.base import get_db
from backend.db.models import User
from backend.auth.dependencies import get_current_user
from backend.orchestrators.qa_orchestrator import (
    AskRequest,
    AskResponse,
    answer_question,
    RepoNotFoundError,
    LLMServiceError
)
from backend.llm.parsing import LLMParsingError

logger = logging.getLogger("loom.routes.qa")

router = APIRouter(tags=["qa"])

@router.post("/ask", response_model=AskResponse)
async def ask(
    request: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Handles user questions about indexed repositories.
    Conforms to PRD Section 5.3 contract.
    """
    try:
        if not request.question or not request.question.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="question is required"
            )

        return await answer_question(request, current_user, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Request: {str(e)}"
        )
    except RepoNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="repo not indexed"
        )
    except LLMParsingError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM response parsing failed: {str(e)}"
        )
    except LLMServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM call failed"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception(f"Unexpected error in /ask route: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
