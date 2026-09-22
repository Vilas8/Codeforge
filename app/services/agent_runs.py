from datetime import datetime, timezone
from app.database.client import supabase


class AgentRunService:
    @staticmethod
    def start(user_id, project_id, mode, workflow, model):
        row = {
            "user_id": user_id,
            "project_id": project_id,
            "mode": mode,
            "workflow": workflow,
            "model": model,
            "status": "running",
            "metadata": {},
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        result = supabase.table("agent_runs").insert(row).execute()
        return result.data[0] if result.data else None

    @staticmethod
    def finish(run_id, status, metadata=None):
        result = supabase.table("agent_runs").update({
            "status": status,
            "metadata": metadata or {},
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", run_id).execute()
        return result.data[0] if result.data else None

    @staticmethod
    def list(user_id, project_id, limit=30):
        result = supabase.table("agent_runs").select("*").eq("user_id", user_id).eq("project_id", project_id).order("started_at", desc=True).limit(min(limit, 100)).execute()
        return result.data or []
