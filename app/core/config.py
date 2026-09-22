from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # CodeForge talks to exactly one inference endpoint. FreeLLMAPI owns
    # provider credentials, model routing, quotas, health and fallback.
    free_llm_api_url: str = "http://localhost:3001/v1"
    free_llm_api_key: Optional[str] = None
    free_llm_api_wire_api: str = "chat_completions"
    free_llm_api_timeout: float = 120.0
    free_llm_api_max_retries: int = 1

    # Task-level routing. These are FreeLLMAPI virtual model IDs by default.
    # They do not name a provider and can be changed without CodeForge changes.
    default_model: str = "auto:balanced"
    planning_model: Optional[str] = "auto:smart"
    coding_model: Optional[str] = "auto:balanced"
    review_model: Optional[str] = "auto:smart"
    debug_model: Optional[str] = "auto:reliable"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

