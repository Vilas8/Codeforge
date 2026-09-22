import asyncio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.projects.workspace import WorkspaceManager
from app.services.jobs import PlatformJobService

router = APIRouter()


@router.post("/{project_id}/index")
async def queue_index(project_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    job = PlatformJobService.enqueue(user.id, project_id, "workspace_index")
    background_tasks.add_task(PlatformJobService.execute, job)
    return job


@router.get("/{project_id}/{job_id}")
async def get_job(project_id: str, job_id: str, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    job = PlatformJobService.get(user.id, project_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
