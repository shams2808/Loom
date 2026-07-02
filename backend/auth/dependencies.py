import uuid
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.base import get_db
from backend.db.models import User
from backend.db import crud
from backend.auth.jwt_handler import decode_access_token

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """
    FastAPI dependency that extracts the JWT from the httpOnly cookie 'session_token',
    validates it, and fetches the current user from the database.
    """
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
        )
    
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
        )
        
    user_id = payload["sub"]
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user session format.",
        )
    
    user = await crud.get_user_by_id(db, user_uuid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user session not found.",
        )
        
    return user
