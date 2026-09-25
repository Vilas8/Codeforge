from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.projects.workspace import WorkspaceManager
from app.services.git import GitService
from app.services.audit import AuditService
from app.services.checkpoints import WorkspaceCheckpointService

router = APIRouter()

def project_workspace(user_id, project_id):
    if not ProjectRepository.get_by_id(user_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
    if not workspace.exists():
        WorkspaceManager.create_temporary_workspace(user_id, project_id)
    return workspace

@router.get("/{project_id}/status")
async def git_status(project_id: str, user=Depends(get_current_user)):
    workspace = project_workspace(user.id, project_id)
    result = await GitService.status(workspace)
    AuditService.record(user.id, project_id, "git.status", "success" if result["success"] else "error")
    return result

@router.get("/{project_id}/diff")
async def git_diff(project_id: str, user=Depends(get_current_user)):
    workspace = project_workspace(user.id, project_id)
    result = await GitService.diff(workspace)
    AuditService.record(user.id, project_id, "git.diff", "success" if result["success"] else "error")
    return result

@router.get("/{project_id}/log")
async def git_log(project_id: str, user=Depends(get_current_user)):
    workspace = project_workspace(user.id, project_id)
    result = await GitService.log(workspace)
    AuditService.record(user.id, project_id, "git.log", "success" if result["success"] else "error")
    return result

class CommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=200)

@router.post("/{project_id}/commit")
async def git_commit(project_id: str, request: CommitRequest, user=Depends(get_current_user)):
    workspace = project_workspace(user.id, project_id)
    checkpoint = None
    try:
        checkpoint = WorkspaceCheckpointService.create(user.id, project_id)
    except Exception:
        pass
    with WorkspaceManager.workspace_lock(user.id, project_id):
        result = await GitService.commit(workspace, request.message)
        if result["success"]:
            WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
    AuditService.record(
        user.id, project_id, "git.commit", "success" if result["success"] else "error",
        {"message": request.message[:200], "checkpoint_id": checkpoint["id"] if checkpoint else None},
    )
    return {**result, "checkpoint_id": checkpoint["id"] if checkpoint else None}
