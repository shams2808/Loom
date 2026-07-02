import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from main import app
from backend.auth.dependencies import get_current_user
from backend.db.base import get_db, Base
from backend.db.models import User, IndexedRepo

DB_FILE = "test_review_endpoint.db"
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
            repo = IndexedRepo(
                id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                user_id=user.id,
                github_repo_id=98765,
                repo_full_name="testuser/testrepo",
                vector_collection_name="repo_98765",
                status="ready",
                chunk_count=50
            )
            db.add_all([user, repo])
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
            await db.execute(delete(IndexedRepo))
            await db.execute(delete(User))
            await db.commit()
    asyncio.run(clean_data())

@patch("backend.orchestrators.review_orchestrator.retrieve_context")
@patch("backend.orchestrators.review_orchestrator.LLMClient")
def test_review_endpoint_happy_path(mock_llm_client_cls, mock_retrieve):
    mock_retrieve.return_value = []
    
    mock_llm_instance = AsyncMock()
    # Mock per-file review
    mock_llm_instance.complete.side_effect = [
        # Response for file review 1
        '{"comments": [{"line": 10, "severity": "warning", "text": "Incorrect loop index"}]}',
        # Response for summary
        '* **Core Changes**:\n  1. Fix loop index\n* **Architectural Impact**:\n  1. None\n* **Testing & Verification**:\n  1. Added test'
    ]
    mock_llm_client_cls.return_value = mock_llm_instance

    response = client.post("/review", json={
        "repo_id": "22222222-2222-2222-2222-222222222222",
        "pr_title": "Fix loops",
        "pr_description": "Fixing some minor index issues",
        "diff": [
            {"file": "src/loop.js", "patch": "@@ -10,3 +10,3 @@\n- for (let i = 0; i <= arr.length; i++) {\n+ for (let i = 0; i < arr.length; i++) {", "status": "modified"}
        ]
    })

    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data["comments"]) == 1
    assert res_data["comments"][0]["file"] == "src/loop.js"
    assert res_data["comments"][0]["line"] == 10
    assert "loop index" in res_data["summary"]

def test_review_endpoint_empty_diff():
    response = client.post("/review", json={
        "repo_id": None,
        "pr_title": "Test Title",
        "pr_description": "Test Desc",
        "diff": []
    })
    assert response.status_code == 400
    assert response.json()["error"] == "diff is required"

@patch("backend.orchestrators.review_orchestrator.retrieve_context")
@patch("backend.orchestrators.review_orchestrator.LLMClient")
def test_review_endpoint_basic_review(mock_llm_client_cls, mock_retrieve):
    mock_llm_instance = AsyncMock()
    mock_llm_instance.complete.side_effect = [
        '{"comments": [{"line": 5, "severity": "info", "text": "Clean code!"}]}',
        '* **Core Changes**:\n  1. Basic summary'
    ]
    mock_llm_client_cls.return_value = mock_llm_instance

    # Passing null repo_id triggers basic review
    response = client.post("/review", json={
        "repo_id": None,
        "pr_title": "Basic PR",
        "pr_description": "Checking basic reviews",
        "diff": [
            {"file": "main.py", "patch": "print('hello')", "status": "added"}
        ]
    })

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["context_aware"] is False
    assert len(res_data["comments"]) == 1
    assert mock_retrieve.call_count == 0  # Should NOT invoke retrieval since repo_id is None
