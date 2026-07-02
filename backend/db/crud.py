import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from backend.db.models import User, IndexedRepo, Conversation, Message

# User CRUD
async def get_user_by_github_id(db: AsyncSession, github_id: int) -> Optional[User]:
    result = await db.execute(select(User).filter(User.github_id == github_id))
    return result.scalars().first()

async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalars().first()

async def upsert_user(
    db: AsyncSession, 
    github_id: int, 
    username: str, 
    avatar_url: Optional[str], 
    access_token_encrypted: str
) -> User:
    user = await get_user_by_github_id(db, github_id)
    if user:
        user.github_username = username
        user.avatar_url = avatar_url
        user.access_token_encrypted = access_token_encrypted
    else:
        user = User(
            github_id=github_id,
            github_username=username,
            avatar_url=avatar_url,
            access_token_encrypted=access_token_encrypted
        )
        db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# Repository CRUD
async def get_indexed_repo(db: AsyncSession, user_id: uuid.UUID, github_repo_id: int) -> Optional[IndexedRepo]:
    result = await db.execute(
        select(IndexedRepo).filter(
            IndexedRepo.user_id == user_id,
            IndexedRepo.github_repo_id == github_repo_id
        )
    )
    return result.scalars().first()

async def get_indexed_repo_by_id(db: AsyncSession, user_id: uuid.UUID, repo_id: uuid.UUID) -> Optional[IndexedRepo]:
    result = await db.execute(
        select(IndexedRepo).filter(
            IndexedRepo.id == repo_id,
            IndexedRepo.user_id == user_id
        )
    )
    return result.scalars().first()

async def get_indexed_repos_by_user(db: AsyncSession, user_id: uuid.UUID) -> List[IndexedRepo]:
    result = await db.execute(select(IndexedRepo).filter(IndexedRepo.user_id == user_id))
    return list(result.scalars().all())

async def create_indexed_repo(
    db: AsyncSession,
    user_id: uuid.UUID,
    github_repo_id: int,
    repo_full_name: str,
    vector_collection_name: str,
    status: str = "pending"
) -> IndexedRepo:
    repo = IndexedRepo(
        user_id=user_id,
        github_repo_id=github_repo_id,
        repo_full_name=repo_full_name,
        vector_collection_name=vector_collection_name,
        status=status
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo

async def update_repo_status(
    db: AsyncSession,
    repo_db_id: uuid.UUID,
    status: str,
    chunk_count: int = 0,
    last_commit_sha: Optional[str] = None,
    last_indexed_at = None
) -> Optional[IndexedRepo]:
    result = await db.execute(select(IndexedRepo).filter(IndexedRepo.id == repo_db_id))
    repo = result.scalars().first()
    if repo:
        repo.status = status
        repo.chunk_count = chunk_count
        if last_commit_sha is not None:
            repo.last_commit_sha = last_commit_sha
        if last_indexed_at is not None:
            repo.last_indexed_at = last_indexed_at
        await db.commit()
        await db.refresh(repo)
    return repo

async def delete_indexed_repo(db: AsyncSession, repo_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    repo = await get_indexed_repo_by_id(db, user_id, repo_id)
    if repo:
        await db.delete(repo)
        await db.commit()
        return True
    return False

# Conversation CRUD
async def get_conversation(db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Conversation]:
    result = await db.execute(
        select(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id
        )
    )
    return result.scalars().first()

async def get_latest_conversation_by_repo(db: AsyncSession, user_id: uuid.UUID, repo_id: uuid.UUID) -> Optional[Conversation]:
    result = await db.execute(
        select(Conversation).filter(
            Conversation.user_id == user_id,
            Conversation.repo_id == repo_id
        ).order_by(Conversation.created_at.desc()).limit(1)
    )
    return result.scalars().first()

async def get_conversations_by_repo(db: AsyncSession, user_id: uuid.UUID, repo_id: uuid.UUID) -> List[Conversation]:
    result = await db.execute(
        select(Conversation).filter(
            Conversation.user_id == user_id,
            Conversation.repo_id == repo_id
        ).order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())

async def create_conversation(db: AsyncSession, user_id: uuid.UUID, repo_id: uuid.UUID) -> Conversation:
    conversation = Conversation(
        user_id=user_id,
        repo_id=repo_id
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation

async def delete_conversation(db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    conversation = await get_conversation(db, conversation_id, user_id)
    if conversation:
        await db.delete(conversation)
        await db.commit()
        return True
    return False

async def rename_conversation(db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, title: str) -> Optional[Conversation]:
    conversation = await get_conversation(db, conversation_id, user_id)
    if conversation:
        conversation.title = title
        await db.commit()
        await db.refresh(conversation)
    return conversation

# Message CRUD
async def get_messages_by_conversation(db: AsyncSession, conversation_id: uuid.UUID) -> List[Message]:
    result = await db.execute(
        select(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    )
    return list(result.scalars().all())

async def create_message(
    db: AsyncSession, 
    conversation_id: uuid.UUID, 
    role: str, 
    content: str, 
    sources: Optional[list] = None
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        sources=sources
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message
