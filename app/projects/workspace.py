import os
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path
from app.projects.storage import SupabaseProjectStorage

WORKSPACE_BASE = Path(os.getenv("WORKSPACE_BASE", "/tmp/workspaces"))

class WorkspaceManager:
    _locks = {}
    _locks_guard = threading.Lock()

    @classmethod
    def _get_lock(cls, user_id: str, project_id: str):
        key = (str(user_id), str(project_id))
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @classmethod
    @contextmanager
    def workspace_lock(cls, user_id: str, project_id: str):
        lock = cls._get_lock(user_id, project_id)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @staticmethod
    def normalize_relative_path(relative_path: str, allow_empty: bool = False) -> str:
        if not isinstance(relative_path, str):
            raise ValueError('Path must be a string.')
        value = relative_path.strip().replace(chr(92), '/').strip('/')
        if allow_empty and value in {'', '.'}:
            return ''
        parts = [part for part in value.split('/') if part]
        if not value and allow_empty:
            return ''
        if not parts or any(part in {'.', '..'} or part.startswith('.') for part in parts):
            raise ValueError('Invalid workspace path.')
        return '/'.join(parts)

    @staticmethod
    def get_workspace_path(user_id: str, project_id: str) -> Path:
        for value, label in ((user_id, "user_id"), (project_id, "project_id")):
            if not isinstance(value, str) or not value.strip() or value in {".", ".."}:
                raise ValueError(f"Invalid {label}.")
            candidate = Path(value)
            if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.parts[0] in {".", ".."}:
                raise ValueError(f"Invalid {label}.")
        return WORKSPACE_BASE / user_id / project_id

    @staticmethod
    def safe_path(user_id: str, project_id: str, relative_path: str, allow_empty: bool = False) -> Path:
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id).resolve()
        normalized = WorkspaceManager.normalize_relative_path(relative_path, allow_empty=allow_empty)
        target = (workspace / normalized).resolve()
        try:
            target.relative_to(workspace)
        except ValueError as exc:
            raise ValueError("Path escapes the workspace.") from exc
        return target

    @classmethod
    def create_temporary_workspace(cls, user_id: str, project_id: str):
        with cls.workspace_lock(user_id, project_id):
            return cls._create_temporary_workspace(user_id, project_id)

    @staticmethod
    def _create_temporary_workspace(user_id: str, project_id: str):
        """Creates local workspace and syncs files from Supabase."""
        workspace_dir = WorkspaceManager.get_workspace_path(user_id, project_id)
        workspace_dir.mkdir(parents=True, exist_ok=True)
    
        prefix = f"{user_id}/{project_id}/files"
        files = SupabaseProjectStorage.list_files(prefix)
    
        # Rehydrate from storage so deleted files from previous agent runs
        # cannot survive in the local temporary workspace.
        safe_files = []
        storage_names = set()
        for item in files:
            name = item.get("name", "")
            if not name or name == ".emptyFolderPlaceholder":
                continue
            try:
                normalized = cls.normalize_relative_path(name)
                target = cls.safe_path(user_id, project_id, normalized)
            except (TypeError, ValueError):
                raise RuntimeError("Invalid project storage path.")
            if target.exists() and target.is_dir():
                raise RuntimeError("Project storage path conflicts with a directory.")
            safe_files.append((normalized, target))
            storage_names.add(normalized)

        for root, dirs, local_files in os.walk(workspace_dir, topdown=True, followlinks=False):
            for dirname in list(dirs):
                local_dir = Path(root) / dirname
                if local_dir.is_symlink():
                    local_dir.unlink()
                    dirs.remove(dirname)
            for filename in local_files:
                local_path = Path(root) / filename
                relative_name = str(local_path.relative_to(workspace_dir)).replace("\\", "/")
                if relative_name not in storage_names:
                    local_path.unlink()

        for normalized, file_path in safe_files:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            storage_path = f"{prefix}/{normalized}"
            content = SupabaseProjectStorage.download_file(storage_path)
            with open(file_path, "wb") as out:
                out.write(content)
    
        return workspace_dir
    
    @classmethod
    def sync_workspace_to_storage(cls, user_id: str, project_id: str):
        with cls.workspace_lock(user_id, project_id):
            return cls._sync_workspace_to_storage(user_id, project_id)

    @staticmethod
    def _sync_workspace_to_storage(user_id: str, project_id: str):
        """Uploads local workspace changes back to Supabase."""
        workspace_dir = WorkspaceManager.get_workspace_path(user_id, project_id)
        if not workspace_dir.exists():
            return
    
        prefix = f"{user_id}/{project_id}/files"
    
        local_names = set()
        for root, _, files in os.walk(workspace_dir):
            for file in files:
                local_path = Path(root) / file
                relative_path = local_path.relative_to(workspace_dir)
                relative_name = str(relative_path).replace("\\", "/")
                local_names.add(relative_name)
                storage_path = f"{prefix}/{relative_name}"
    
                with open(local_path, "rb") as f:
                    SupabaseProjectStorage.upload_file(storage_path, f.read())
    
        # Storage is durable; remove objects that no longer exist locally.
        remote_files = SupabaseProjectStorage.list_files(prefix)
        stale_paths = [
            f"{prefix}/{item['name']}"
            for item in remote_files
            if item.get("name") not in local_names
            and item.get("name") != ".emptyFolderPlaceholder"
        ]
        if stale_paths:
            SupabaseProjectStorage.delete_files(stale_paths)
    
    @staticmethod
    def cleanup_workspace(user_id: str, project_id: str):
        """Deletes the temporary workspace for one authenticated project."""
        workspace_dir = WorkspaceManager.get_workspace_path(user_id, project_id)
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
