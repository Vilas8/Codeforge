from typing import Literal
from openai import AsyncOpenAI
from app.core.config import settings

# CodeForge intentionally has one upstream provider from its point of view:
# the private FreeLLMAPI gateway. Provider/model selection happens there.
Provider = Literal["freellmapi"]


def _require_gateway_key() -> str:
    key = settings.free_llm_api_key
    if not key:
        raise RuntimeError(
            "FREE_LLM_API_KEY is not configured. "
            "Configure the unified FreeLLMAPI gateway key in the CodeForge environment."
        )
    return key


def get_ai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_require_gateway_key(),
        base_url=settings.free_llm_api_url.rstrip("/") + "/",
        timeout=settings.free_llm_api_timeout,
        max_retries=settings.free_llm_api_max_retries,
    )


def get_model(task: str = "coding") -> str:
    """Resolve a CodeForge task to a FreeLLMAPI routing model/profile."""
    configured = {
        "planning": settings.planning_model,
        "coding": settings.coding_model,
        "review": settings.review_model,
        "debug": settings.debug_model,
    }.get(task)

    return configured or settings.default_model


def get_provider_for_model(model: str) -> Provider:
    """Backward-compatible label for persisted metadata.

    The actual provider is intentionally NOT inferred from the model name.
    FreeLLMAPI performs provider selection, health checks and fallback.
    """
    if not (model or "").strip():
        raise ValueError("Model cannot be empty.")
    return "freellmapi"


def get_wire_api(model: str | None = None) -> str:
    """Return the configured OpenAI-compatible wire protocol.

    Chat Completions is the default because it has the broadest compatibility
    for streaming, tools and multimodal requests through FreeLLMAPI.
    """
    return settings.free_llm_api_wire_api


def is_auto_model(model: str) -> bool:
    normalized = (model or "").strip().lower()
    return normalized == "auto" or normalized.startswith("auto:")


def get_gateway_model_catalog(limit: int | None = None):
    """Synchronous helper retained for future admin/model-selector integration."""
    return None
