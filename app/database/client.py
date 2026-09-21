from supabase import create_client, Client
from app.core.config import settings

def get_supabase_client() -> Client:
    """
    Returns a Supabase client using the service role key for backend operations.
    WARNING: This client has admin privileges and bypasses RLS.
    For user-specific actions, RLS must be enforced at the application level 
    or by using the anon key with a set session.
    """
    return create_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key
    )

supabase: Client = get_supabase_client()
