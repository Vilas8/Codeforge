from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    claude_api_key: Optional[str] = None
    claude_api_base_url: str = "https://api.llmsrelay.com/v1"
    claude_model: str = "claude-sonnet-4.6"

    codex_api_key: Optional[str] = None
    codex_api_base_url: str = "https://api.llmsrelay.com/v1"
    codex_model: str = "gpt-5.5"

    universal_api_key: Optional[str] = None
    universal_api_base_url: str = "https://api.llmsrelay.com/v1"
    universal_wire_api: str = "chat_completions"

    default_model: str = "claude-sonnet-4.6"
    planning_model: Optional[str] = None
    coding_model: Optional[str] = None
    review_model: Optional[str] = None
    debug_model: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
