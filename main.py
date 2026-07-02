import logging
from fastapi import FastAPI, Request, status, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import settings

# Setup logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("loom")

app = FastAPI(
    title="Loom Codebase Intelligence Backend",
    description="Unified Q&A and PR Review API backend for Loom Chrome Extension",
    version="1.0.0"
)

# Custom CORS Middleware to handle chrome-extension:// wildcards with credentials=True
class ChromeExtensionCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        is_allowed = False
        
        # Allow Chrome extension origins and local development hosts
        if origin:
            if origin.startswith("chrome-extension://") or "localhost" in origin or "127.0.0.1" in origin:
                is_allowed = True
                
        if request.method == "OPTIONS":
            response = Response()
            if is_allowed:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Cookie, X-Requested-With, Accept"
                response.headers["Access-Control-Max-Age"] = "600"
            return response
            
        response = await call_next(request)
        if is_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Cookie, X-Requested-With, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        return response

app.add_middleware(ChromeExtensionCORSMiddleware)

# Import routes
from backend.routes.health import router as health_router
from backend.routes.auth import router as auth_router
from backend.routes.repos import router as repos_router
from backend.routes.qa import router as qa_router
from backend.routes.review import router as review_router

# Register routes
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(repos_router)
app.include_router(qa_router)
app.include_router(review_router)

# FastAPI HTTPException Handler (PRD Section 5.6 Contract)
@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail if isinstance(exc.detail, str) else "Request error",
            "detail": str(exc.detail) if exc.detail else None
        }
    )

# Request Validation Error Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "Validation Error",
            "detail": str(exc.errors())
        }
    )

# Global Unexpected Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception occurred: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "An unexpected error occurred on the server.",
            "detail": str(exc)
        }
    )

@app.on_event("startup")
async def startup_event():
    import asyncio
    from backend.retrieval.sync import start_auto_sync_loop
    asyncio.create_task(start_auto_sync_loop())

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Loom Backend on port {settings.port}...")
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
