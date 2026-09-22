from __future__ import annotations

from datetime import datetime, timezone
from app.database.client import supabase


class PlatformMetrics:
    @staticmethod
    def record(user_id: str, project_id: str, name: str, value: float, tags: dict | None = None):
        try:
            supabase.table("platform_metrics").insert({
                "user_id": user_id,
                "project_id": project_id,
                "name": name[:100],
                "value": float(value),
                "tags": tags or {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass

    @staticmethod
    def recent(user_id: str, project_id: str, limit: int = 100):
        response = supabase.table("platform_metrics").select("name,value,tags,created_at").eq("user_id", user_id).eq("project_id", project_id).order("created_at", desc=True).limit(max(1, min(limit, 500))).execute()
        return response.data or []
