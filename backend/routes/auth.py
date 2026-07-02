import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.base import get_db
from backend.db import crud
from backend.auth.github_oauth import get_github_login_url, exchange_code_for_token, fetch_github_user_profile
from backend.security.encryption import encrypt_token
from backend.auth.jwt_handler import create_access_token
from backend.auth.dependencies import get_current_user
from backend.db.models import User

logger = logging.getLogger("loom.routes.auth")

router = APIRouter(tags=["auth"])

@router.get("/auth/github/login")
async def github_login():
    """Redirects the browser to GitHub's OAuth2 authorization page."""
    redirect_url = get_github_login_url()
    return RedirectResponse(url=redirect_url)

@router.get("/auth/github/callback")
async def github_callback(
    code: str = None, 
    error: str = None, 
    db: AsyncSession = Depends(get_db)
):
    """
    GitHub OAuth callback. Exchanges auth code for token, retrieves profile info,
    saves the user in the database, and sets an httpOnly session cookie.
    """
    if error:
        logger.warning(f"GitHub OAuth callback returned error: {error}")
        return RedirectResponse(url="/?error=access_denied")
        
    if not code:
        logger.warning("GitHub OAuth callback missing code query parameter.")
        return RedirectResponse(url="/?error=missing_code")

    try:
        # 1. Exchange code
        access_token = await exchange_code_for_token(code)
        
        # 2. Fetch user profile
        user_data = await fetch_github_user_profile(access_token)
        github_id = user_data.get("id")
        github_username = user_data.get("login")
        avatar_url = user_data.get("avatar_url")
        
        if not github_id or not github_username:
            logger.error(f"GitHub profile missing critical fields: {user_data}")
            return RedirectResponse(url="/?error=invalid_profile")

        # 3. Encrypt access token
        encrypted_token = encrypt_token(access_token)

        # 4. Upsert User in DB
        user = await crud.upsert_user(
            db=db,
            github_id=github_id,
            username=github_username,
            avatar_url=avatar_url,
            access_token_encrypted=encrypted_token
        )

        # 5. Issue JWT and set cookie
        jwt_token = create_access_token(user_id=str(user.id), username=user.github_username)
        
        # Redirect to a simple landing page or /
        response = RedirectResponse(url="/")
        response.set_cookie(
            key="session_token",
            value=jwt_token,
            httponly=True,
            max_age=7 * 24 * 3600,  # 7 days
            samesite="lax",
            secure=False  # Local development is HTTP
        )
        return response
    except HTTPException as e:
        logger.error(f"GitHub OAuth Callback HTTP Error: {e.detail}")
        return RedirectResponse(url=f"/?error={e.detail}")
    except Exception as e:
        logger.exception(f"Unexpected error in GitHub callback: {e}")
        return RedirectResponse(url="/?error=internal_server_error")

@router.get("/auth/logout")
async def logout():
    """Logs out the user by clearing the JWT session cookie and returning status JSON."""
    response = JSONResponse(content={"status": "logged out"})
    response.delete_cookie("session_token")
    return response

@router.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Returns current logged-in user profile metadata conforming to the PRD contract."""
    return {
        "github_username": current_user.github_username,
        "avatar_url": current_user.avatar_url
    }

from fastapi.responses import HTMLResponse

@router.get("/", response_class=HTMLResponse)
async def login_success_page():
    return """
    <html>
    <head>
        <title>Loom Login Successful</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: #0d1117;
                color: #c9d1d9;
                text-align: center;
                padding-top: 100px;
            }
            .container {
                max-width: 500px;
                margin: 0 auto;
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 40px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            }
            h1 {
                color: #58a6ff;
                margin-bottom: 20px;
            }
            p {
                font-size: 16px;
                line-height: 1.5;
            }
            .success-icon {
                font-size: 48px;
                color: #3fb950;
                margin-bottom: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">✓</div>
            <h1>Loom Login Successful!</h1>
            <p>You have successfully logged into Loom. You can close this window now and return to GitHub.</p>
            <script>
                setTimeout(function() {
                    window.close();
                }, 2000);
            </script>
        </div>
    </body>
    </html>
    """

