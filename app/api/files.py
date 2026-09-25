import asyncio
from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
import io
import mimetypes
import zipfile
import shutil

from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.projects.workspace import WorkspaceManager
from app.projects.storage import SupabaseProjectStorage
from app.services.audit import AuditService

router = APIRouter()

class FileUpdate(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=200000)

class FolderCreate(BaseModel):
    path: str = Field(min_length=1, max_length=500)

class MoveRequest(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    destination: str = Field(default="", max_length=500)

class RenameRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=255)

class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=12000)
    timeout: int = Field(default=30, ge=1, le=120)

def get_user_project(user_id: str, project_id: str):
    project = ProjectRepository.get_by_id(user_id, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

def safe_target(workspace_dir: Path, relative_path: str) -> Path:
    try:
        normalized = WorkspaceManager.normalize_relative_path(relative_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workspace path.")
    target = (workspace_dir.resolve() / normalized).resolve()
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
    folders = []
    max_entries = 10000
    for root, dirs, files in os.walk(workspace_dir, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for dirname in dirs:
            rel_dir = os.path.relpath(os.path.join(root, dirname), workspace_dir)
            folders.append(rel_dir.replace("\\", "/"))
        for filename in files:
            if filename.startswith("."):
                continue
            rel_path = os.path.relpath(os.path.join(root, filename), workspace_dir)
            if len(tree) + len(folders) >= max_entries:
                break
            tree.append(rel_path.replace("\\", "/"))
        if len(tree) + len(folders) >= max_entries:
            break
    return {"files": sorted(tree), "folders": sorted(folders), "truncated": len(tree) + len(folders) >= max_entries}

@router.get("/{project_id}/file")
async def get_file_content(project_id: str, path: str, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    target = safe_target(workspace_dir, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.stat().st_size > 500000:
        raise HTTPException(status_code=413, detail="File is too large to open in the editor.")
    with open(target, "r", encoding="utf-8") as f:
        return {"content": f.read(500001)}

@router.post("/{project_id}/file/create")
async def create_file(project_id: str, file_data: FileUpdate, user=Depends(get_current_user)):
    """Create a new workspace file without overwriting an existing item."""
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    relative_path = file_data.path.strip().replace("\\", "/").strip("/")
    if not relative_path or relative_path.startswith(".") or any(part.startswith(".") for part in Path(relative_path).parts) or ".." in Path(relative_path).parts:
        raise HTTPException(status_code=400, detail="Enter a safe relative file path.")
    target = safe_target(workspace_dir, relative_path)
    if target.exists():
        raise HTTPException(status_code=409, detail="A file or folder already exists at that path.")
    with WorkspaceManager.workspace_lock(user.id, project_id):
        if target.exists():
            raise HTTPException(status_code=409, detail="A file or folder already exists at that path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(file_data.content)
        WorkspaceManager._sync_workspace_to_storage(user.id, project_id)
    return {"status": "success", "path": relative_path}

@router.put("/{project_id}/file")
async def update_file(project_id: str, file_data: FileUpdate, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    relative_path = file_data.path.strip().replace("\\", "/").strip("/")
    if not relative_path or relative_path.startswith(".") or any(part.startswith(".") for part in Path(relative_path).parts) or ".." in Path(relative_path).parts:
        raise HTTPException(status_code=400, detail="Enter a safe relative file path.")
    target = safe_target(workspace_dir, relative_path)
    if target.exists() and target.is_dir():
        raise HTTPException(status_code=409, detail="A folder already exists at that path.")
    with WorkspaceManager.workspace_lock(user.id, project_id):
        if target.exists() and target.is_dir():
            raise HTTPException(status_code=409, detail="A folder already exists at that path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(file_data.content)
        WorkspaceManager._sync_workspace_to_storage(user.id, project_id)
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
    if target.exists():
        raise HTTPException(status_code=409, detail="A file or folder already exists at that path.")
    with WorkspaceManager.workspace_lock(user.id, project_id):
        if target.exists():
            raise HTTPException(status_code=409, detail="A file or folder already exists at that path.")
        target.mkdir(parents=True, exist_ok=True)

        # Supabase Storage represents folders through files. Keep an otherwise
        # empty directory durable without exposing the marker in the IDE tree.
        marker = target / ".codeforge-folder"
        if not marker.exists():
            marker.write_text("", encoding="utf-8")
        WorkspaceManager._sync_workspace_to_storage(user.id, project_id)
    return {"status": "success", "path": relative_path}


@router.post("/{project_id}/move")
async def move_workspace_item(project_id: str, move_data: MoveRequest, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    source_path = move_data.source.strip().replace("\\", "/").strip("/")
    destination_path = move_data.destination.strip().replace("\\", "/").strip("/")
    if not source_path or source_path.startswith(".") or any(part.startswith(".") for part in Path(source_path).parts):
        raise HTTPException(status_code=400, detail="Invalid source path.")
    if destination_path and (destination_path.startswith(".") or any(part.startswith(".") for part in Path(destination_path).parts)):
        raise HTTPException(status_code=400, detail="Invalid destination folder.")
    if ".." in Path(source_path).parts or ".." in Path(destination_path).parts:
        raise HTTPException(status_code=400, detail="Invalid workspace path.")
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    source = safe_target(workspace_dir, source_path)
    destination_dir = safe_target(workspace_dir, destination_path) if destination_path else workspace_dir
    with WorkspaceManager.workspace_lock(user.id, project_id):
        if not source.exists():
            raise HTTPException(status_code=404, detail="Source file or folder not found.")
        if not destination_dir.exists() or not destination_dir.is_dir():
            raise HTTPException(status_code=404, detail="Destination folder not found.")
        if source == destination_dir:
            raise HTTPException(status_code=400, detail="An item cannot be moved into itself.")
        if source.is_dir():
            try:
                destination_dir.resolve().relative_to(source.resolve())
                raise HTTPException(status_code=400, detail="A folder cannot be moved inside itself.")
            except ValueError:
                pass
        target = destination_dir / source.name
        if target.exists():
            raise HTTPException(status_code=409, detail="An item with that name already exists there.")
        shutil.move(str(source), str(target))
        WorkspaceManager._sync_workspace_to_storage(user.id, project_id)
    return {"status": "success", "source": source_path, "destination": target.relative_to(workspace_dir).as_posix()}
@router.post("/{project_id}/rename")
async def rename_workspace_item(project_id: str, payload: RenameRequest, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    source_path = payload.path.strip().replace("\\", "/").strip("/")
    new_name = payload.name.strip()
    if not source_path or not new_name or "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="Enter a valid item name.")
    if new_name in {".", ".."} or new_name.startswith("."):
        raise HTTPException(status_code=400, detail="Hidden or reserved names are not allowed.")
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    source = safe_target(workspace_dir, source_path)
    with WorkspaceManager.workspace_lock(user.id, project_id):
        if not source.exists():
            raise HTTPException(status_code=404, detail="Item not found.")
        target = safe_target(workspace_dir, (source.parent / new_name).relative_to(workspace_dir).as_posix())
        if target.exists():
            raise HTTPException(status_code=409, detail="An item with that name already exists.")
        source.rename(target)
        WorkspaceManager._sync_workspace_to_storage(user.id, project_id)
    return {"status": "success", "source": source_path, "destination": target.relative_to(workspace_dir).as_posix()}
@router.delete("/{project_id}/item")
async def delete_workspace_item(project_id: str, path: str, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    item_path = path.strip().replace("\\", "/").strip("/")
    if not item_path or ".." in Path(item_path).parts:
        raise HTTPException(status_code=400, detail="Invalid workspace path.")
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    target = safe_target(workspace_dir, item_path)
    with WorkspaceManager.workspace_lock(user.id, project_id):
        if not target.exists():
            raise HTTPException(status_code=404, detail="Item not found.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        WorkspaceManager._sync_workspace_to_storage(user.id, project_id)
    return {"status": "success", "path": item_path}
@router.delete("/{project_id}/file")
async def delete_file(project_id: str, path: str, user=Depends(get_current_user)):
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    target = safe_target(workspace_dir, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    with WorkspaceManager.workspace_lock(user.id, project_id):
        target.unlink()
        WorkspaceManager._sync_workspace_to_storage(user.id, project_id)
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
    """Download a bounded ZIP archive of the authenticated project workspace."""
    get_user_project(user.id, project_id)
    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    if not workspace_dir.exists():
        await asyncio.to_thread(WorkspaceManager.create_temporary_workspace, user.id, project_id)

    max_files = 5000
    max_archive_bytes = 200 * 1024 * 1024
    max_source_bytes = 250 * 1024 * 1024
    archive = io.BytesIO()
    source_bytes = 0
    file_count = 0

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for root, dirs, files in os.walk(workspace_dir, topdown=True, followlinks=False):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and not (Path(root) / d).is_symlink()
            ]
            for filename in files:
                if filename in {".codeforge-agent.lock", ".codeforge-folder"} or filename.startswith("."):
                    continue
                source = Path(root) / filename
                if source.is_symlink():
                    continue
                try:
                    size = source.stat().st_size
                except OSError:
                    continue
                if file_count >= max_files or source_bytes + size > max_source_bytes:
                    raise HTTPException(status_code=413, detail="Project is too large to export.")
                source_bytes += size
                file_count += 1
                relative = source.relative_to(workspace_dir).as_posix()
                bundle.write(source, relative)
                if archive.tell() > max_archive_bytes:
                    raise HTTPException(status_code=413, detail="Project archive is too large to export.")

    archive.seek(0)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(project_id))[:60]
    return StreamingResponse(
        iter([archive.getvalue()]),
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


@router.get("/{project_id}/terminal/status")
async def terminal_status(project_id: str, user=Depends(get_current_user)):
    """Return whether the configured terminal execution backend is available."""
    get_user_project(user.id, project_id)
    from app.core.config import settings
    mode = str(settings.execution_mode or "docker").lower()
    if mode == "process":
        return {
            "ready": True,
            "mode": "process",
            "label": "Trusted process",
            "detail": "Commands run in the application process environment. Use only for trusted/private development.",
        }
    docker_available = shutil.which("docker") is not None
    return {
        "ready": docker_available,
        "mode": "docker",
        "label": "Docker sandbox" if docker_available else "Docker unavailable",
        "detail": "Isolated Docker execution is ready." if docker_available else "The current service does not have a Docker daemon/CLI available. Configure a dedicated execution service or use EXECUTION_MODE=process only for trusted development.",
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
