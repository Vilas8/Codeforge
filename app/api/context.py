from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.security import get_current_user
from app.projects.workspace import WorkspaceManager
from app.services.context import WorkspaceContextService
from app.services.checkpoints import WorkspaceCheckpointService
from app.database.repositories.projects import ProjectRepository

router = APIRouter()


class ContextRequest(BaseModel):
    directives: list[str] = Field(default_factory=lambda: ["@workspace"])
    selection: dict | None = None


class CheckpointRequest(BaseModel):
    action: str = "create"
    checkpoint_id: str | None = None


def _project_or_404(user, project_id):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/context")
async def workspace_context(project_id: str, req: ContextRequest, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    return WorkspaceContextService.build(user.id, project_id, req.directives, req.selection)


@router.post("/{project_id}/checkpoint")
async def checkpoint(project_id: str, req: CheckpointRequest, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    if req.action == "create":
        return {"action": "created", "checkpoint": WorkspaceCheckpointService.create(user.id, project_id)}
    if req.action == "restore" and req.checkpoint_id:
        manifest = WorkspaceCheckpointService.restore(user.id, project_id, req.checkpoint_id)
        WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
        return {"action": "restored", "checkpoint": manifest}
    raise HTTPException(status_code=400, detail="Use action=create or action=restore with checkpoint_id")
