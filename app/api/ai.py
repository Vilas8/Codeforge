from fastapi import APIRouter, Depends, HTTPException
from app.ai.client import get_ai_client
from app.core.security import get_current_user

router = APIRouter()


@router.get("/status")
async def ai_gateway_status(user=Depends(get_current_user)):
    """Return a safe readiness signal for the configured FreeLLMAPI gateway.

    Provider credentials and internal routing details are intentionally not
    returned to the browser. This endpoint only proves that CodeForge can
    authenticate to the gateway and read its model catalog.
    """
    try:
        client = get_ai_client()
        models = await client.models.list()
        model_count = len(getattr(models, "data", []) or [])
        return {
            "status": "ready",
            "gateway": "freellmapi",
            "model_count": model_count,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "gateway": "freellmapi",
                "message": str(exc),
            },
        )
