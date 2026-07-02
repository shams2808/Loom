import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from backend.config import settings

logger = logging.getLogger("loom.auth.jwt")

JWT_SECRET = settings.jwt_secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

def create_access_token(user_id: str, username: str) -> str:
    """
    Creates a signed JWT access token containing internal user identity.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire
    }
    encoded_jwt = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    """
    Decodes and validates a JWT token. Returns the payload dictionary if valid, else None.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token signature expired.")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT token decoding failed: {e}")
        return None
