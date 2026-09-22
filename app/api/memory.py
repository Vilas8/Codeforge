from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.services.memory import ProjectMemoryService

router = APIRouter()


def _check(user, project_id):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")


class MemoryRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=12000)
    source: str = "user"


@router.get("/{project_id}")
async def list_memory(project_id: str, user=Depends(get_current_user)):
    _check(user, project_id)
    return {"memories": ProjectMemoryService.list(user.id, project_id)}


@router.get("/{project_id}/search")
async def search_memory(project_id: str, q: str = "", limit: int = 8, user=Depends(get_current_user)):
    _check(user, project_id)
    return {"query": q, "results": ProjectMemoryService.search(user.id, project_id, q, limit)}


@router.post("/{project_id}")
async def add_memory(project_id: str, req: MemoryRequest, user=Depends(get_current_user)):
    _check(user, project_id)
    return ProjectMemoryService.add(user.id, project_id, req.kind, req.content, req.source)


@router.delete("/{project_id}/{memory_id}")
async def delete_memory(project_id: str, memory_id: str, user=Depends(get_current_user)):
    _check(user, project_id)
    ProjectMemoryService.delete(user.id, project_id, memory_id)
    return {"deleted": True}
