import uuid
import logging
from typing import Optional, List
from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db import crud
from backend.db.models import User, Message
from backend.retrieval.interface import retrieve_context, ContextChunk
from backend.llm.client import LLMClient
from backend.llm.parsing import validate_and_parse, LLMParsingError
from backend.prompts.qa_prompts import build_qa_system_prompt, build_qa_user_prompt

logger = logging.getLogger("loom.orchestrator.qa")

# Pydantic Schemas
class AskRequest(BaseModel):
    repo_id: str = Field(..., description="The database UUID of the repository to ask about")
    question: str = Field(..., min_length=1, description="The question about the codebase")
    conversation_id: Optional[str] = Field(None, description="Optional conversation UUID for continuity")
    current_file: Optional[str] = Field(None, description="The file path the user is currently viewing")

class Source(BaseModel):
    file: str = Field(..., description="File path relative to repository root")
    function_name: Optional[str] = Field(None, description="Function/class name if identified")
    line_start: int = Field(..., description="Starting line number (1-indexed)")
    line_end: int = Field(..., description="Ending line number (1-indexed)")

class AskResponse(BaseModel):
    answer: str = Field(..., description="Grounded LLM-generated answer")
    sources: List[Source] = Field(..., description="List of source file sections used in the answer")
    conversation_id: str = Field(..., description="Conversation UUID for continuity")

class LLMAnswerSchema(BaseModel):
    answer: str = Field(..., description="Grounded answer to user question")
    sources: List[Source] = Field(default_factory=list, description="Cited file sources")

# Exceptions
class RepoNotFoundError(Exception):
    pass

class LLMServiceError(Exception):
    pass

async def answer_question(request: AskRequest, current_user: User, db: AsyncSession) -> AskResponse:
    """
    Orchestrates the codebase Q&A process.
    """
    repo_id = request.repo_id
    question = request.question.strip()
    conversation_id_str = request.conversation_id

    if not question:
        raise ValueError("Question cannot be empty or only whitespace.")

    try:
        repo_uuid = uuid.UUID(repo_id)
    except ValueError:
        raise ValueError("Invalid repository ID format.")

    # 1. Check Repository Ownership
    repo = await crud.get_indexed_repo_by_id(db, current_user.id, repo_uuid)
    if not repo:
        logger.warning(f"Access denied: User '{current_user.github_username}' tried to query repo ID '{repo_id}'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to query this repository."
        )

    if repo.status != "ready":
        raise RepoNotFoundError(f"Repository is not ready. Current status: {repo.status}")

    # 2. Resolve Conversation History
    conversation = None
    if conversation_id_str:
        try:
            conv_uuid = uuid.UUID(conversation_id_str)
            conversation = await crud.get_conversation(db, conv_uuid, current_user.id)
            if not conversation:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: Conversation not found."
                )
        except ValueError:
            raise ValueError("Invalid conversation ID format.")
            
    if not conversation:
        conversation = await crud.create_conversation(db, current_user.id, repo.id)

    # Load recent conversation history (last 6 messages / 3 turns)
    messages = await crud.get_messages_by_conversation(db, conversation.id)
    recent_messages = messages[-6:] if len(messages) > 6 else messages
    history = [{"role": m.role, "content": m.content} for m in recent_messages]

    # 3. Context Retrieval
    try:
        # Pass include_callers=False to retrieve_context in Q&A mode
        context_chunks = await retrieve_context(
            query=question,
            repo_id=str(repo.id),
            user_id=str(current_user.id),
            top_k=8,
            include_callers=False,
            current_file=request.current_file
        )
    except Exception as e:
        logger.exception(f"Error during context retrieval: {e}")
        context_chunks = []

    # 4. Prompt Construction
    system_prompt = build_qa_system_prompt()
    user_prompt = build_qa_user_prompt(question, context_chunks, history)

    # 5. LLM Call
    if not settings.gemini_api_key:
        raise LLMServiceError("GEMINI_API_KEY is not configured on the server.")

    client = LLMClient(api_key=settings.gemini_api_key, model=settings.llm_model)
    
    try:
        logger.info(f"Calling LLM for repo '{repo.repo_full_name}', conversation '{conversation.id}'...")
        raw_response = await client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3
        )
    except Exception as e:
        logger.exception(f"LLM API Call failed: {e}")
        raise LLMServiceError(f"LLM completion failed due to API error: {str(e)}")

    # 6. Parse Response
    try:
        parsed_answer = validate_and_parse(raw_response, LLMAnswerSchema)
    except LLMParsingError as e:
        logger.exception(f"LLM Response JSON parsing failed: {e}")
        raise e

    # 7. Save Messages in DB
    await crud.create_message(db, conversation.id, "user", question)
    sources_json = [s.model_dump() for s in parsed_answer.sources]
    await crud.create_message(db, conversation.id, "assistant", parsed_answer.answer, sources_json)

    return AskResponse(
        answer=parsed_answer.answer,
        sources=parsed_answer.sources,
        conversation_id=str(conversation.id)
    )
