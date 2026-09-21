from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user
from app.database.client import supabase_auth

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(req: LoginRequest):
    try:
        res = supabase_auth.auth.sign_in_with_password({
            "email": req.email,
            "password": req.password,
        })
        if not res.session or not res.session.access_token:
            raise HTTPException(status_code=401, detail="Authentication succeeded but no session was returned.")
        return {
            "access_token": res.session.access_token,
            "user": {
                "id": res.user.id if res.user else None,
                "email": res.user.email if res.user else req.email,
            },
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
