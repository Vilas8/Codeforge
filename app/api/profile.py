from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.database.client import supabase
from app.database.repositories.projects import ProjectRepository

router = APIRouter()

class ProfileUpdate(BaseModel):
    display_name: str = Field(default="", max_length=80)
    avatar_url: str | None = Field(default=None, max_length=500)

@router.get("")
async def get_profile(user=Depends(get_current_user)):
    ProjectRepository.ensure_profile(user.id, getattr(user, "email", None))
    result = supabase.table("profiles").select("id,email,display_name,avatar_url,created_at,updated_at").eq("id", user.id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return result.data[0]

@router.patch("")
async def update_profile(payload: ProfileUpdate, user=Depends(get_current_user)):
    ProjectRepository.ensure_profile(user.id, getattr(user, "email", None))
    display_name = payload.display_name.strip()
    avatar_url = (payload.avatar_url or "").strip() or None
    if avatar_url and not avatar_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Avatar URL must start with http:// or https://")
    result = supabase.table("profiles").update({
        "display_name": display_name or None,
        "avatar_url": avatar_url,
    }).eq("id", user.id).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Could not update profile")
    return result.data[0]
