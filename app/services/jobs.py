from __future__ import annotations

from datetime import datetime, timezone
from app.database.client import supabase
from app.services.indexer import WorkspaceIndexService


class PlatformJobService:
    @staticmethod
    def enqueue(user_id: str, project_id: str, kind: str, payload: dict | None = None):
        active = (
            supabase.table("platform_jobs")
            .select("*")
            .eq("user_id", user_id)
            .eq("project_id", project_id)
            .eq("kind", kind)
            .in_("status", ["queued", "running"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if active.data:
            return active.data[0]
        row = {"user_id": user_id, "project_id": project_id, "kind": kind[:60], "payload": payload or {}}
        response = supabase.table("platform_jobs").insert(row).execute()
        return (response.data or [row])[0]

    @staticmethod
    def get(user_id: str, project_id: str, job_id: str):
        response = supabase.table("platform_jobs").select("*").eq("id", job_id).eq("user_id", user_id).eq("project_id", project_id).limit(1).execute()
        return (response.data or [None])[0]

    @staticmethod
    async def execute(job: dict):
        job_id = job["id"]
        supabase.table("platform_jobs").update({
            "status": "running", "started_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", job_id).execute()
        try:
            if job["kind"] == "workspace_index":
                result = await WorkspaceIndexService.build_semantic(job["user_id"], job["project_id"])
            else:
                raise ValueError("Unsupported platform job: " + str(job["kind"]))
            supabase.table("platform_jobs").update({
                "status": "completed", "result": result,
                "finished_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", job_id).execute()
        except Exception as exc:
            supabase.table("platform_jobs").update({
                "status": "error", "error": "Job execution failed.",
                "finished_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", job_id).execute()
