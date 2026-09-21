import os
import shutil
from pathlib import Path
from app.projects.storage import SupabaseProjectStorage

WORKSPACE_BASE = Path(os.getenv("WORKSPACE_BASE", "/tmp/workspaces"))

class WorkspaceManager:
    @staticmethod
    def get_workspace_path(user_id: str, project_id: str) -> Path:
        return WORKSPACE_BASE / user_id / project_id

    @staticmethod
    def create_temporary_workspace(user_id: str, project_id: str):
        """Creates local workspace and syncs files from Supabase."""
        workspace_dir = WorkspaceManager.get_workspace_path(user_id, project_id)
        workspace_dir.mkdir(parents=True, exist_ok=True)

        prefix = f"{user_id}/{project_id}/files"
        files = SupabaseProjectStorage.list_files(prefix)

        # Rehydrate from storage so deleted files from previous agent runs
        # cannot survive in the local temporary workspace.
        storage_names = {
            f["name"] for f in files
            if f.get("name") != ".emptyFolderPlaceholder"
        }
        for root, _, local_files in os.walk(workspace_dir):
            for filename in local_files:
                local_path = Path(root) / filename
                relative_name = str(local_path.relative_to(workspace_dir)).replace("\\", "/")
                if relative_name not in storage_names:
                    local_path.unlink()

        for f in files:
            if f["name"] == ".emptyFolderPlaceholder":
                continue
            file_path = workspace_dir / f["name"]
            file_path.parent.mkdir(parents=True, exist_ok=True)

            storage_path = f"{prefix}/{f['name']}"
            content = SupabaseProjectStorage.download_file(storage_path)
            with open(file_path, "wb") as out:
                out.write(content)

        return workspace_dir

    @staticmethod
    def sync_workspace_to_storage(user_id: str, project_id: str):
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
