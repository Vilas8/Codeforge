from datetime import datetime, timedelta, timezone
from uuid import uuid4
from app.database.client import supabase
from app.core.config import settings


class AIUsageLimitError(Exception):
    def __init__(self, message: str, code: str = "ai_limit_exceeded"):
        super().__init__(message)
        self.code = code


class AIUsageService:
    @staticmethod
    def new_request_id() -> str:
        return str(uuid4())

    @staticmethod
    def _day_start() -> str:
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    @staticmethod
    def _limit(user_id: str, field: str, default: int):
        try:
            result = (
                supabase.table("ai_limits")
                .select(field)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data and result.data[0].get(field) is not None:
                return int(result.data[0][field])
        except Exception:
            # Limits are an optional database feature during migration.
            # Fall back to environment defaults rather than breaking chat.
            pass
        return default

    @staticmethod
    def _usage_since(user_id: str, since: str):
        try:
            result = (
                supabase.table("ai_usage")
                .select("request_id,total_tokens,status")
                .eq("user_id", user_id)
                .gte("created_at", since)
                .execute()
            )
            rows = result.data or []
            return len(rows), sum(int(row.get("total_tokens") or 0) for row in rows)
        except Exception:
            return 0, 0

    @staticmethod
    def enforce_daily_request_limit(user_id: str):
        request_limit = AIUsageService._limit(
            user_id, "daily_request_limit", settings.ai_daily_request_limit
        )
        requests, _ = AIUsageService._usage_since(user_id, AIUsageService._day_start())
        if request_limit > 0 and requests >= request_limit:
            raise AIUsageLimitError(
                f"Daily AI request limit reached ({request_limit}).",
                "daily_request_limit",
            )

    @staticmethod
    def record(
        *,
        request_id: str,
        user_id: str,
        project_id: str,
        model: str,
        task: str,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: int = 0,
        error_code: str | None = None,
    ):
        payload = {
            "request_id": request_id,
            "user_id": user_id,
            "project_id": project_id,
            "model": model,
            "task": task,
            "status": status,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "duration_ms": int(duration_ms or 0),
            "error_code": error_code,
        }
        try:
            return supabase.table("ai_usage").insert(payload).execute()
        except Exception:
            # Usage telemetry must never take down a successful coding task.
            return None

    @staticmethod
    def summary(user_id: str, days: int = 7):
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))).isoformat()
        try:
            result = (
                supabase.table("ai_usage")
                .select("model,task,status,input_tokens,output_tokens,total_tokens,duration_ms,created_at")
                .eq("user_id", user_id)
                .gte("created_at", since)
                .order("created_at", desc=True)
                .limit(1000)
                .execute()
            )
            rows = result.data or []
            return {
                "days": days,
                "requests": len(rows),
                "successful_requests": sum(1 for r in rows if r.get("status") == "success"),
                "failed_requests": sum(1 for r in rows if r.get("status") == "error"),
                "input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
                "output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
                "total_tokens": sum(int(r.get("total_tokens") or 0) for r in rows),
                "rows": rows,
            }
        except Exception:
            return {
                "days": days,
                "requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "rows": [],
            }
