from fastapi import APIRouter, Depends, Query
from app.core.security import get_current_user
from app.database.client import supabase

router = APIRouter()

@router.get("")
async def audit_logs(limit: int = Query(100, ge=1, le=500), user=Depends(get_current_user)):
    result = supabase.table("audit_logs").select("id,project_id,action,status,metadata,created_at").eq("user_id", user.id).order("created_at", desc=True).limit(limit).execute()
    return {"logs": result.data or []}
