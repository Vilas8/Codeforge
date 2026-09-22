from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.projects.workspace import WorkspaceManager
from app.services.indexer import WorkspaceIndexService

router = APIRouter()

@router.post("/{project_id}/build")
async def build_index(project_id: str, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    return await WorkspaceIndexService.build_semantic(user.id, project_id)

@router.get("/{project_id}/search")
async def search_index(project_id: str, q: str, limit: int = 12, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"query": q, "results": await WorkspaceIndexService.search_hybrid(user.id, project_id, q, limit)}
