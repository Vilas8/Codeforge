import asyncio
from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import io
import mimetypes
import zipfile

from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.projects.workspace import WorkspaceManager
from app.projects.storage import SupabaseProjectStorage
from app.services.audit import AuditService

router = APIRouter()

class FileUpdate(BaseModel):
    path: str
    content: str

class FolderCreate(BaseModel):
    path: str

class CommandRequest(BaseModel):
    command: str
    timeout: int = 30

def get_user_project(user_id: str, project_id: str):
    project = ProjectRepository.get_by_id(user_id, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

def safe_target(workspace_dir: Path, relative_path: str) -> Path:
    target = (workspace_dir / relative_path).resolve()
    try:
        target.relative_to(workspace_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid path")
    return target

@router.get("/{project_id}/tree")
async def get_project_tree(project_id: str, user=Depends(get_current_user)):
    """Returns the authenticated user's file tree for the project."""
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    if not workspace_dir.exists():
        WorkspaceManager.create_temporary_workspace(user.id, project_id)

    tree = []
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for filename in files:
            if filename.startswith("."):
                continue
            rel_path = os.path.relpath(os.path.join(root, filename), workspace_dir)
            tree.append(rel_path.replace("\\", "/"))
    return {"files": sorted(tree)}

@router.get("/{project_id}/file")
async def get_file_content(project_id: str, path: str, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    target = safe_target(workspace_dir, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    with open(target, "r", encoding="utf-8") as f:
        return {"content": f.read()}

@router.put("/{project_id}/file")
async def update_file(project_id: str, file_data: FileUpdate, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    target = safe_target(workspace_dir, file_data.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(file_data.content)

    WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
    return {"status": "success"}

@router.post("/{project_id}/folder")
async def create_folder(project_id: str, folder_data: FolderCreate, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    relative_path = folder_data.path.strip().replace("\\", "/").strip("/")
    if not relative_path or relative_path.startswith(".") or "/." in relative_path or ".." in Path(relative_path).parts:
        raise HTTPException(status_code=400, detail="Enter a safe relative folder path.")

    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    target = safe_target(workspace_dir, relative_path)
    if target.exists() and not target.is_dir():
        raise HTTPException(status_code=409, detail="A file already exists at that path.")
    target.mkdir(parents=True, exist_ok=True)

    # Supabase Storage represents folders through files. Keep an otherwise
    # empty directory durable without exposing the marker in the IDE tree.
    marker = target / ".codeforge-folder"
    if not marker.exists():
        marker.write_text("", encoding="utf-8")

    WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
    return {"status": "success", "path": relative_path}


@router.delete("/{project_id}/file")
async def delete_file(project_id: str, path: str, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    target = safe_target(workspace_dir, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink()
    WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
    return {"status": "success"}


@router.get("/{project_id}/download")
async def download_project_file(project_id: str, path: str, user=Depends(get_current_user)):
    """Download one real workspace file for the authenticated project."""
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    target = safe_target(workspace_dir, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name,
        headers={"Content-Disposition": f'attachment; filename="{target.name}"'},
    )

@router.get("/{project_id}/download-all")
async def download_project_zip(project_id: str, user=Depends(get_current_user)):
    """Download the complete authenticated project workspace as a ZIP archive."""
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    if not workspace_dir.exists():
        await asyncio.to_thread(WorkspaceManager.create_temporary_workspace, user.id, project_id)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for filename in files:
                if filename in {".codeforge-agent.lock", ".codeforge-folder"} or filename.startswith("."):
                    continue
                source = Path(root) / filename
                relative = source.relative_to(workspace_dir).as_posix()
                bundle.write(source, relative)
    archive.seek(0)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(project_id))[:60]
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="codeforge-{safe_name}.zip"'},
    )

@router.get("/{project_id}/storage")
async def get_storage_usage(project_id: str, user=Depends(get_current_user)):
    """Return live storage usage for this project's workspace."""
    get_user_project(user.id, project_id)
    prefix = f"{user.id}/{project_id}/files"
    entries = SupabaseProjectStorage.list_files(prefix)
    used = 0
    count = 0
    for entry in entries:
        metadata = entry.get("metadata") or {}
        size = metadata.get("size") or metadata.get("contentLength") or metadata.get("content_length") or 0
        try:
            used += int(size)
        except (TypeError, ValueError):
            pass
        count += 1
    return {
        "used_bytes": used,
        "file_count": count,
        "project_limit_bytes": 5 * 1024 * 1024 * 1024,
    }


@router.post("/{project_id}/terminal")
async def run_project_command(project_id: str, request: CommandRequest, user=Depends(get_current_user)):
    """Run a bounded command inside the authenticated project's workspace."""
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    if not workspace_dir.exists():
        await asyncio.to_thread(WorkspaceManager.create_temporary_workspace, user.id, project_id)
    from app.services.executor import CommandExecutor
    result = await CommandExecutor.run(workspace_dir, request.command, request.timeout)
    AuditService.record(user.id, project_id, "terminal.execute", "success" if result["success"] else "error", {"sandbox": True, "command_length": len(request.command), "exit_code": result["code"]})
    return result
