import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    app_env: str = "development"
    
    # Supabase config
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    
    # Universal API config
    universal_api_key: str
    universal_api_base_url: str
    default_model: str
    
    # Optional specific models
    planning_model: Optional[str] = None
    coding_model: Optional[str] = None
    review_model: Optional[str] = None
    debug_model: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
