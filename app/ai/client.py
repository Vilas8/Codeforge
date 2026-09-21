from typing import Literal
from openai import AsyncOpenAI
from app.core.config import settings

Provider = Literal["claude", "codex"]

def _resolve_key(provider: Provider) -> str:
    key = settings.claude_api_key if provider == "claude" else settings.codex_api_key
    key = key or settings.universal_api_key
    if not key:
        raise RuntimeError(f"No API key configured for {provider}.")
    return key

def _resolve_base_url(provider: Provider) -> str:
    return settings.claude_api_base_url if provider == "claude" else settings.codex_api_base_url

def get_provider_for_model(model: str) -> Provider:
    normalized = (model or "").strip().lower()
    if normalized.startswith("claude-"):
        return "claude"
    if normalized.startswith("gpt-") or normalized.startswith("codex"):
        return "codex"
    raise ValueError(f"Unsupported model '{model}'. Use Claude (claude-*) or Codex/OpenAI (gpt-* / codex*).")

def get_ai_client(provider: Provider) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=_resolve_key(provider), base_url=_resolve_base_url(provider))

def get_model(task: str = "coding") -> str:
    if task == "planning" and settings.planning_model:
        return settings.planning_model
    if task == "review" and settings.review_model:
        return settings.review_model
    if task == "debug" and settings.debug_model:
        return settings.debug_model
    if task == "coding" and settings.coding_model:
        return settings.coding_model
    return settings.default_model

def get_wire_api(model: str) -> str:
    return "responses" if get_provider_for_model(model) == "codex" else "chat_completions"
