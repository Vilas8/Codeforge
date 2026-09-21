from supabase import create_client, Client
from app.core.config import settings

# Service-role client: backend persistence/admin operations only.
supabase: Client = create_client(
    supabase_url=settings.supabase_url,
    supabase_key=settings.supabase_service_role_key,
)

# Auth client: anon key keeps user authentication separate from the
# service-role client's privileged session.
supabase_auth: Client = create_client(
    supabase_url=settings.supabase_url,
    supabase_key=settings.supabase_anon_key,
)
