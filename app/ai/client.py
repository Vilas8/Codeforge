from openai import AsyncOpenAI
from app.core.config import settings

def get_ai_client() -> AsyncOpenAI:
    """
    Initializes the OpenAI-compatible Universal API client.
    """
    return AsyncOpenAI(
        api_key=settings.universal_api_key,
        base_url=settings.universal_api_base_url
    )

ai_client = get_ai_client()

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
