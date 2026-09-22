from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.services.metrics import PlatformMetrics

router = APIRouter()

@router.get("/{project_id}")
async def metrics(project_id: str, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"metrics": PlatformMetrics.recent(user.id, project_id)}
