from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.services.audit import AuditService
from app.services.change_sets import ChangeSetError, WorkspaceChangeSetService

router = APIRouter()


def _project_or_404(user, project_id):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")


class ChangeSetAction(BaseModel):
    action: str


@router.get("/{project_id}")
async def list_change_sets(project_id: str, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    return {"change_sets": WorkspaceChangeSetService.list(user.id, project_id)}


@router.get("/{project_id}/{change_set_id}")
async def get_change_set(project_id: str, change_set_id: str, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    try:
        return WorkspaceChangeSetService.get(user.id, project_id, change_set_id)
    except ChangeSetError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{project_id}/{change_set_id}/action")
async def change_set_action(project_id: str, change_set_id: str, req: ChangeSetAction, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    try:
        if req.action == "accept":
            result = WorkspaceChangeSetService.accept(user.id, project_id, change_set_id)
        elif req.action == "reject":
            result = WorkspaceChangeSetService.reject_all(user.id, project_id, change_set_id)
        else:
            raise HTTPException(status_code=400, detail="Supported actions: accept, reject")
        AuditService.record(user.id, project_id, "changeset." + req.action, "success", {"change_set_id": change_set_id})
        return result
    except ChangeSetError as exc:
        AuditService.record(user.id, project_id, "changeset." + req.action, "error", {"change_set_id": change_set_id, "error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{project_id}/{change_set_id}/files/{file_path:path}/accept")
async def accept_change_set_file(project_id: str, change_set_id: str, file_path: str, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    try:
        result = WorkspaceChangeSetService.accept_file(user.id, project_id, change_set_id, file_path)
        AuditService.record(user.id, project_id, "changeset.file_accept", "success", {"change_set_id": change_set_id, "path": file_path})
        return result
    except ChangeSetError as exc:
        AuditService.record(user.id, project_id, "changeset.file_accept", "error", {"change_set_id": change_set_id, "path": file_path, "error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{project_id}/{change_set_id}/files/{file_path:path}/reject")
async def reject_change_set_file(project_id: str, change_set_id: str, file_path: str, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    try:
        result = WorkspaceChangeSetService.reject_file(user.id, project_id, change_set_id, file_path)
        AuditService.record(user.id, project_id, "changeset.file_reject", "success", {"change_set_id": change_set_id, "path": file_path})
        return result
    except ChangeSetError as exc:
        AuditService.record(user.id, project_id, "changeset.file_reject", "error", {"change_set_id": change_set_id, "path": file_path, "error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc))
