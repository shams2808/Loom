import logging
import httpx
from fastapi import HTTPException, status
from backend.config import settings

logger = logging.getLogger("loom.auth.github_oauth")

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"

def get_github_login_url() -> str:
    """Constructs the GitHub authorization URL to redirect users."""
    if not settings.github_client_id:
        logger.error("GITHUB_CLIENT_ID setting is not configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub OAuth Client ID is not configured on the server."
        )
    params = {
        "client_id": settings.github_client_id,
        "scope": "repo",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GITHUB_AUTH_URL}?{query_string}"

async def exchange_code_for_token(code: str) -> str:
    """Exchanges an authorization code for a GitHub access token."""
    if not settings.github_client_id or not settings.github_client_secret:
        logger.error("GitHub OAuth credentials are not fully configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub OAuth credentials are not configured on the server."
        )

    async with httpx.AsyncClient() as client:
        token_headers = {"Accept": "application/json"}
        token_payload = {
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
        }
        try:
            token_resp = await client.post(GITHUB_TOKEN_URL, headers=token_headers, data=token_payload)
            token_resp.raise_for_status()
            token_data = token_resp.json()
        except Exception as e:
            logger.exception(f"Failed to post to GitHub token exchange: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub token exchange failed: {str(e)}"
            )

        access_token = token_data.get("access_token")
        if not access_token:
            logger.error(f"GitHub token response missing access_token: {token_data}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub API did not return an access token: {token_data.get('error_description', 'unknown error')}"
            )
        return access_token

async def fetch_github_user_profile(access_token: str) -> dict:
    """Retrieves user profile details from GitHub API."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "Loom-Backend/1.0"
    }
    async with httpx.AsyncClient() as client:
        try:
            user_resp = await client.get(GITHUB_USER_API, headers=headers)
            user_resp.raise_for_status()
            return user_resp.json()
        except Exception as e:
            logger.exception(f"Failed to fetch user profile from GitHub API: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub profile fetch failed: {str(e)}"
            )
