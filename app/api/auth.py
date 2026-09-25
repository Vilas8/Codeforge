from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user
from app.database.client import supabase_auth

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/login")
async def login(req: LoginRequest):
    try:
        res = supabase_auth.auth.sign_in_with_password({"email": req.email, "password": req.password})
        return {"access_token": res.session.access_token, "refresh_token": res.session.refresh_token, "expires_at": getattr(res.session, "expires_at", None)}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    """Return the currently authenticated user from Supabase."""
    return {"id": user.id, "email": user.email}


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    try:
        res = supabase_auth.auth.refresh_session(req.refresh_token)
        if not res.session or not res.session.access_token:
            raise HTTPException(status_code=401, detail="Refresh token is invalid or expired.")
        return {
            "access_token": res.session.access_token,
            "refresh_token": res.session.refresh_token or req.refresh_token,
            "expires_at": getattr(res.session, "expires_at", None),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Session refresh failed. Please sign in again.")
