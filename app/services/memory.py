from __future__ import annotations

from datetime import datetime, timezone
from app.database.client import supabase


class ProjectMemoryService:
    @staticmethod
    def add(user_id: str, project_id: str, kind: str, content: str, source: str = "user"):
        row = {
            "user_id": user_id,
            "project_id": project_id,
            "kind": kind[:40],
            "content": content[:12000],
            "source": source[:80],
        }
        response = supabase.table("project_memory").insert(row).execute()
        return (response.data or [row])[0]

    @staticmethod
    def list(user_id: str, project_id: str, limit: int = 30):
        response = (
            supabase.table("project_memory")
            .select("id,kind,content,source,created_at,updated_at")
            .eq("user_id", user_id)
            .eq("project_id", project_id)
            .order("updated_at", desc=True)
            .limit(max(1, min(limit, 100)))
            .execute()
        )
        return response.data or []

    @staticmethod
    def search(user_id: str, project_id: str, query: str, limit: int = 8):
        tokens = [x.lower() for x in query.split() if len(x) > 2]
        if not tokens:
            return []
        rows = ProjectMemoryService.list(user_id, project_id, 100)
        scored = []
        for row in rows:
            hay = row.get("content", "").lower()
            score = sum(hay.count(token) for token in tokens)
            if score:
                scored.append({**row, "score": score})
        scored.sort(key=lambda x: (-x["score"], x.get("updated_at", "")))
        return scored[:max(1, min(limit, 20))]

    @staticmethod
    def delete(user_id: str, project_id: str, memory_id: str):
        return (
            supabase.table("project_memory")
            .delete()
            .eq("id", memory_id)
            .eq("user_id", user_id)
            .eq("project_id", project_id)
            .execute()
        )
