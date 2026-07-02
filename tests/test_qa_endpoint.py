import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from main import app
from backend.auth.dependencies import get_current_user
from backend.db.base import get_db, Base
from backend.db.models import User, IndexedRepo, Conversation, Message

DB_FILE = "test_qa_endpoint.db"
db_url = f"sqlite+aiosqlite:///{DB_FILE}"
engine = create_async_engine(db_url, echo=False)
AsyncSessionLocalTest = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    import os
    import asyncio
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
        except:
            pass
            
    async def init_db():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init_db())
    yield
    async def cleanup_db():
        await engine.dispose()
        if os.path.exists(DB_FILE):
            try:
                os.remove(DB_FILE)
            except:
                pass
    asyncio.run(cleanup_db())

@pytest.fixture(autouse=True)
def configure_dependencies_and_data():
    import asyncio
    async def insert_data():
        async with AsyncSessionLocalTest() as db:
            user = User(
                id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                github_id=12345,
                github_username="testuser",
                access_token_encrypted="encrypted_token_here"
            )
            # Ready repo
            repo = IndexedRepo(
                id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                user_id=user.id,
                github_repo_id=98765,
                repo_full_name="testuser/testrepo",
                vector_collection_name="repo_98765",
                status="ready",
                chunk_count=50
            )
            # Non-ready repo
            repo_pending = IndexedRepo(
                id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
                user_id=user.id,
                github_repo_id=54321,
                repo_full_name="testuser/pendingrepo",
                vector_collection_name="repo_54321",
                status="indexing",
                chunk_count=0
            )
            db.add_all([user, repo, repo_pending])
            await db.commit()
    asyncio.run(insert_data())
        
    async def override_get_db():
        async with AsyncSessionLocalTest() as session:
            yield session
            
    async def override_get_current_user():
        async with AsyncSessionLocalTest() as session:
            from sqlalchemy.future import select
            result = await session.execute(select(User).filter(User.github_username == "testuser"))
            return result.scalars().first()
            
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    
    yield
    
    app.dependency_overrides.clear()
    
    async def clean_data():
        async with AsyncSessionLocalTest() as db:
            from sqlalchemy import delete
            await db.execute(delete(Message))
            await db.execute(delete(Conversation))
            await db.execute(delete(IndexedRepo))
            await db.execute(delete(User))
            await db.commit()
    asyncio.run(clean_data())

@patch("backend.orchestrators.qa_orchestrator.retrieve_context")
@patch("backend.orchestrators.qa_orchestrator.LLMClient")
def test_ask_endpoint_happy_path(mock_llm_client_cls, mock_retrieve):
    mock_chunk = MagicMock()
    mock_chunk.file = "src/auth.js"
    mock_chunk.function_name = "login"
    mock_chunk.code = "function login() { return 'ok'; }"
    mock_chunk.line_start = 10
    mock_chunk.line_end = 15
    mock_chunk.score = 0.95
    mock_chunk.relation = "similar"
    mock_retrieve.return_value = [mock_chunk]

    mock_llm_instance = AsyncMock()
    mock_llm_instance.complete.return_value = (
        '{"answer": "Login is defined in src/auth.js.", '
        '"sources": [{"file": "src/auth.js", "function_name": "login", "line_start": 10, "line_end": 15}]}'
    )
    mock_llm_client_cls.return_value = mock_llm_instance

    response = client.post("/ask", json={
        "repo_id": "22222222-2222-2222-2222-222222222222",
        "question": "where is login handled?",
        "conversation_id": None
    })

    assert response.status_code == 200
    res_data = response.json()
    assert "Login is defined in src/auth.js" in res_data["answer"]
    assert len(res_data["sources"]) == 1
    assert res_data["sources"][0]["file"] == "src/auth.js"
    assert "conversation_id" in res_data

def test_ask_endpoint_unindexed_repo():
    response = client.post("/ask", json={
        "repo_id": "33333333-3333-3333-3333-333333333333",
        "question": "what is this?"
    })
    assert response.status_code == 400
    assert response.json()["error"] == "repo not indexed"

def test_ask_endpoint_unauthenticated():
    # Remove auth override
    app.dependency_overrides[get_current_user] = get_current_user
    client.cookies.clear()
    
    response = client.post("/ask", json={
        "repo_id": "22222222-2222-2222-2222-222222222222",
        "question": "hello"
    })
    assert response.status_code == 401
