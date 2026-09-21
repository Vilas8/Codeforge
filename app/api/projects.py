from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository

router = APIRouter()

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    slug: str

@router.post("/")
async def create_project(project: ProjectCreate, user=Depends(get_current_user)):
    res = ProjectRepository.create(user.id, project.name, project.description, project.slug)
    if not res:
        raise HTTPException(status_code=400, detail="Could not create project")
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
    ProjectRepository.delete(user.id, project_id)
    return {"status": "deleted"}
