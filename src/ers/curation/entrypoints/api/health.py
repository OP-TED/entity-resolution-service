from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint to verify the service is running."""
    return {"status": "ok"}
