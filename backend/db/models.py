import uuid
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.db.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    github_id = Column(BigInteger, unique=True, nullable=False)
    github_username = Column(String(255), nullable=False)
    avatar_url = Column(Text, nullable=True)
    access_token_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    repos = relationship("IndexedRepo", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")

class IndexedRepo(Base):
    __tablename__ = "indexed_repos"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    github_repo_id = Column(BigInteger, nullable=False)
    repo_full_name = Column(String(255), nullable=False)
    vector_collection_name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, indexing, ready, failed
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)
    last_commit_sha = Column(String(40), nullable=True)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="repos")
    conversations = relationship("Conversation", back_populates="repo", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_id", "github_repo_id", name="uq_user_repo"),
    )

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    repo_id = Column(Uuid, ForeignKey("indexed_repos.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    title = Column(String(255), nullable=True)

    # Relationships
    user = relationship("User", back_populates="conversations")
    repo = relationship("IndexedRepo", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id = Column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)  # JSON-serialized citations
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
