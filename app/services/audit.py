from datetime import datetime, timezone
from app.database.client import supabase

class AuditService:
    @staticmethod
    def record(user_id, project_id, action, status="success", metadata=None):
        try:
            return supabase.table("audit_logs").insert({
                "user_id": user_id,
                "project_id": project_id,
                "action": action,
                "status": status,
                "metadata": metadata or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            return None
