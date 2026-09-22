from fastapi import APIRouter, Depends, HTTPException, Query
from app.ai.client import get_ai_client
from app.core.security import get_current_user
from app.core.config import settings
from app.services.usage import AIUsageService

router = APIRouter()


@router.get("/status")
async def ai_gateway_status(user=Depends(get_current_user)):
    try:
        client = get_ai_client()
        models = await client.models.list()
        model_count = len(getattr(models, "data", []) or [])
        return {
            "status": "ready",
            "gateway": "freellmapi",
            "model_count": model_count,
            "default_model": settings.default_model,
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


@router.get("/models")
async def ai_gateway_models(user=Depends(get_current_user)):
    try:
        client = get_ai_client()
        models = await client.models.list()
        data = getattr(models, "data", []) or []
        return {
            "gateway": "freellmapi",
            "models": [
                {
                    "id": getattr(model, "id", None),
                    "owned_by": getattr(model, "owned_by", None),
                }
                for model in data
                if getattr(model, "id", None)
            ],
            "routing_profiles": [
                {"id": "auto:fast", "label": "Fast", "description": "Prioritize latency."},
                {"id": "auto:smart", "label": "Smart", "description": "Prioritize reasoning quality."},
                {"id": "auto:balanced", "label": "Balanced", "description": "Balance quality and latency."},
                {"id": "auto:coding", "label": "Coding", "description": "Prioritize coding-capable models."},
                {"id": "auto:reliable", "label": "Reliable", "description": "Prioritize availability."},
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI gateway unavailable: {exc}")


@router.get("/usage")
async def ai_usage(days: int = Query(default=7, ge=1, le=90), user=Depends(get_current_user)):
    return AIUsageService.summary(user.id, days)


@router.get("/limits")
async def ai_limits(user=Depends(get_current_user)):
    return {
        "daily_request_limit": AIUsageService._limit(
            user.id, "daily_request_limit", settings.ai_daily_request_limit
        ),
        "daily_token_limit": AIUsageService._limit(
            user.id, "daily_token_limit", settings.ai_daily_token_limit
        ),
    }
