import pytest
import uuid
from unittest.mock import patch

from backend.db.base import AsyncSessionLocal, Base, engine
from backend.db import crud
from backend.db.models import User
from backend.retrieval.interface import retrieve_context
from backend.retrieval.vector_store import upsert_chunks, delete_collection, get_chroma_client

DB_FILE = "test_retrieval_isolation.db"
db_url = f"sqlite+aiosqlite:///{DB_FILE}"

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    import os
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine
    
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
        except:
            pass
            
    # Swap out engine URL for the test run
    # (Since this test doesn't use FastAPI, we configure it manually)
    async def init_db():
        test_engine = create_async_engine(db_url, echo=False)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await test_engine.dispose()
        
    asyncio.run(init_db())
    yield
    
    async def cleanup_db():
        if os.path.exists(DB_FILE):
            try:
                os.remove(DB_FILE)
            except:
                pass
    asyncio.run(cleanup_db())

@pytest.mark.asyncio
@patch("backend.retrieval.embeddings.embed_batch")
async def test_user_retrieval_isolation(mock_embed):
    # Mock embeddings: return static vector
    mock_embed.return_value = [[0.1] * 384]

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    test_engine = create_async_engine(db_url, echo=False)
    AsyncSessionLocalTest = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with AsyncSessionLocalTest() as db:
        # Create User A
        user_a = User(
            id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            github_id=111,
            github_username="usera",
            access_token_encrypted="tokena"
        )
        # Create User B
        user_b = User(
            id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            github_id=222,
            github_username="userb",
            access_token_encrypted="tokenb"
        )
        db.add_all([user_a, user_b])
        await db.commit()
        await db.refresh(user_a)
        await db.refresh(user_b)

        # User A indexes "shams2808/Loom"
        repo_a_coll = f"user_aaaaaaaa_aaaa_aaaa_aaaa_aaaaaaaaaaaa_shams2808_loom"
        repo_a = await crud.create_indexed_repo(
            db=db,
            user_id=user_a.id,
            github_repo_id=123456,
            repo_full_name="shams2808/Loom",
            vector_collection_name=repo_a_coll,
            status="ready"
        )

        # User B indexes "shams2808/Loom"
        repo_b_coll = f"user_bbbbbbbb_bbbb_bbbb_bbbb_bbbbbbbbbbbb_shams2808_loom"
        repo_b = await crud.create_indexed_repo(
            db=db,
            user_id=user_b.id,
            github_repo_id=123456,
            repo_full_name="shams2808/Loom",
            vector_collection_name=repo_b_coll,
            status="ready"
        )

        # Add unique chunks to each user's collection
        chunk_a = [{"file": "main.py", "function_name": "usera_func", "code": "def usera_only(): pass", "line_start": 1, "line_end": 2}]
        chunk_b = [{"file": "main.py", "function_name": "userb_func", "code": "def userb_only(): pass", "line_start": 1, "line_end": 2}]

        upsert_chunks(repo_a.vector_collection_name, chunk_a, [[0.1] * 384])
        upsert_chunks(repo_b.vector_collection_name, chunk_b, [[0.1] * 384])

        # Query User A's collection using retrieve_context
        # Patch the base engine session to use our test db inside retrieve_context
        with patch("backend.retrieval.interface.AsyncSessionLocal", AsyncSessionLocalTest):
            res_a = await retrieve_context(
                query="usera_only",
                repo_id=str(repo_a.id),
                user_id=str(user_a.id),
                top_k=5,
                include_callers=False
            )
            assert len(res_a) == 1
            assert res_a[0].function_name == "usera_func"
            assert "usera_only" in res_a[0].code

            # Verify that query for User A does NOT return User B's content
            res_a_b = await retrieve_context(
                query="userb_only",
                repo_id=str(repo_a.id),
                user_id=str(user_a.id),
                top_k=5,
                include_callers=False
            )
            # Since the collection is isolated, query vector similarity might return User A's chunk (closest match in its own collection) but NEVER User B's chunk
            for r in res_a_b:
                assert "userb_only" not in r.code
                assert r.function_name != "userb_func"

        # Cleanup collections
        delete_collection(repo_a.vector_collection_name)
        delete_collection(repo_b.vector_collection_name)

    await test_engine.dispose()
