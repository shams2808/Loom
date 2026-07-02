from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
async def health():
    """Conforms to PRD Section 5.5 contract."""
    return {"status": "ok", "version": "1.0.0"}
