from fastapi import APIRouter, Depends, HTTPException
from app.ai.client import get_ai_client
from app.core.security import get_current_user
from app.services.agent import MODE_CONFIG

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


@router.get("/modes")
async def ai_agent_modes(user=Depends(get_current_user)):
    """Return the agent modes and their safe execution policies for the IDE."""
    return {
        "modes": [
            {
                "id": mode_id,
                "label": cfg["label"],
                "task": cfg["task"],
                "max_steps": cfg["max_steps"],
                "max_tool_calls": cfg["max_tool_calls"],
                "max_file_changes": cfg["max_file_changes"],
                "read_only": cfg["max_file_changes"] == 0,
            }
            for mode_id, cfg in MODE_CONFIG.items()
        ]
    }
