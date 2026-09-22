from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.services.test_diagnostics import TestDiagnosticsParser

router = APIRouter()


class DiagnosticsRequest(BaseModel):
    output: str = Field(default="", max_length=100000)
    status: str = "unknown"


@router.post("/{project_id}/parse")
async def parse_diagnostics(project_id: str, req: DiagnosticsRequest, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return TestDiagnosticsParser.summarize(req.output, req.status)


@router.get("/{project_id}")
async def list_test_runs(project_id: str, limit: int = 20, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    from app.database.client import supabase
    response = supabase.table("test_runs").select("*").eq("user_id", user.id).eq("project_id", project_id).order("created_at", desc=True).limit(max(1, min(limit, 100))).execute()
    return {"runs": response.data or []}
