import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from main import app
from backend.security.encryption import encrypt_token, decrypt_token
from backend.auth.jwt_handler import create_access_token, decode_access_token
from backend.db.base import get_db, Base
from backend.db.models import User
from backend.auth.dependencies import get_current_user

# Test encryption
def test_encryption_roundtrip():
    token = "gho_test_12345"
    enc = encrypt_token(token)
    assert enc != token
    assert decrypt_token(enc) == token

# Test JWT
def test_jwt_roundtrip():
    user_id = str(uuid.uuid4())
    username = "testuser"
    token = create_access_token(user_id, username)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["username"] == username

# DB setup for router tests
DB_FILE = "test_auth_routes.db"
db_url = f"sqlite+aiosqlite:///{DB_FILE}"
engine = create_async_engine(db_url, echo=False)
AsyncSessionLocalTest = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

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
def configure_overrides():
    async def override_get_db():
        async with AsyncSessionLocalTest() as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()

def test_auth_me_unauthenticated():
    client = TestClient(app)
    # Clear any cookies
    client.cookies.clear()
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert "error" in response.json()

def test_auth_me_authenticated():
    # Insert a dummy user in test db
    import asyncio
    async def insert_user():
        async with AsyncSessionLocalTest() as db:
            user = User(
                id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                github_id=99999,
                github_username="realuser",
                avatar_url="https://avatar.url",
                access_token_encrypted="encrypted"
            )
            db.add(user)
            await db.commit()
    asyncio.run(insert_user())

    client = TestClient(app)
    # Generate token
    token = create_access_token("11111111-1111-1111-1111-111111111111", "realuser")
    client.cookies.set("session_token", token)

    response = client.get("/auth/me")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["github_username"] == "realuser"
    assert res_data["avatar_url"] == "https://avatar.url"

def test_logout():
    client = TestClient(app)
    token = create_access_token("11111111-1111-1111-1111-111111111111", "realuser")
    client.cookies.set("session_token", token)
    
    response = client.get("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "logged out"}
    # Assert that Set-Cookie header is returned with max-age=0 or path=/ to delete the session_token cookie
    set_cookie = response.headers.get("set-cookie", "")
    assert "session_token=" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie



