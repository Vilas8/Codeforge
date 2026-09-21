from fastapi import APIRouter, Depends
from app.core.security import get_current_user

router = APIRouter()

@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    """Return the currently authenticated user from Supabase."""
    return {"id": user.id, "email": user.email}
