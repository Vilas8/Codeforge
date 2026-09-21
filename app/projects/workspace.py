import os
import shutil
from pathlib import Path
from app.projects.storage import SupabaseProjectStorage
from app.database.client import supabase

WORKSPACE_BASE = Path(os.getenv("WORKSPACE_BASE", "/tmp/workspaces"))

class WorkspaceManager:
    @staticmethod
    def get_workspace_path(project_id: str) -> Path:
        return WORKSPACE_BASE / project_id

    @staticmethod
    def create_temporary_workspace(user_id: str, project_id: str):
        """Creates local workspace and syncs files from Supabase."""
        workspace_dir = WorkspaceManager.get_workspace_path(project_id)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
        prefix = f"{user_id}/{project_id}/files"
        files = SupabaseProjectStorage.list_files(prefix)
        
        for f in files:
            if f['name'] == '.emptyFolderPlaceholder':
                continue
            file_path = workspace_dir / f['name']
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            storage_path = f"{prefix}/{f['name']}"
            content = SupabaseProjectStorage.download_file(storage_path)
            with open(file_path, "wb") as out:
                out.write(content)
                
        return workspace_dir

    @staticmethod
    def sync_workspace_to_storage(user_id: str, project_id: str):
        """Uploads local workspace changes back to Supabase."""
        workspace_dir = WorkspaceManager.get_workspace_path(project_id)
        if not workspace_dir.exists():
            return
            
        prefix = f"{user_id}/{project_id}/files"
        
        for root, _, files in os.walk(workspace_dir):
            for file in files:
                local_path = Path(root) / file
                relative_path = local_path.relative_to(workspace_dir)
                storage_path = f"{prefix}/{relative_path}"
                
                with open(local_path, "rb") as f:
                    content = f.read()
                    SupabaseProjectStorage.upload_file(storage_path, content)

    @staticmethod
    def cleanup_workspace(project_id: str):
        """Deletes the temporary workspace."""
        workspace_dir = WorkspaceManager.get_workspace_path(project_id)
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
