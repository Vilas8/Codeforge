from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository

router = APIRouter()

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default="", max_length=2000)
    slug: Optional[str] = Field(default=None, max_length=80)

@router.post("/")
async def create_project(project: ProjectCreate, user=Depends(get_current_user)):
    name = project.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name is required.")
    slug = (project.slug or "").strip().lower()
    if not slug:
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:50] or "project"
    try:
        res = ProjectRepository.create(
            user.id,
            name,
            project.description or "",
            slug,
            getattr(user, "email", None),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Could not create project.")
    if not res:
        raise HTTPException(status_code=500, detail="Could not create project")
    return res

@router.get("/")
async def list_projects(user=Depends(get_current_user)):
    return ProjectRepository.get_all(user.id)

@router.get("/{project_id}")
async def get_project(project_id: str, user=Depends(get_current_user)):
    res = ProjectRepository.get_by_id(user.id, project_id)
    if not res:
        raise HTTPException(status_code=404, detail="Project not found")
    return res

@router.delete("/{project_id}")
async def delete_project(project_id: str, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        deleted = ProjectRepository.delete(user.id, project_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not delete project.")
    if not deleted:
        raise HTTPException(status_code=500, detail="Could not delete project.")
    return {"status": "deleted"}
