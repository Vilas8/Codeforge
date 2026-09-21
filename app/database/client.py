from supabase import create_client, Client
from app.core.config import settings


def get_supabase_client() -> Client:
    """Return the service-role client for server-side database/storage operations."""
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key,
    )


def get_supabase_auth_client() -> Client:
    """Return the anon-key client for user authentication/token validation."""
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_anon_key,
    )


supabase: Client = get_supabase_client()
supabase_auth: Client = get_supabase_auth_client()
