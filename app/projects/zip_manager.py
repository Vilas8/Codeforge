import os
import zipfile
import shutil
from pathlib import Path
from fastapi import UploadFile, HTTPException
from app.projects.workspace import WorkspaceManager

class ZipManager:
    @staticmethod
    def extract_zip_to_workspace(project_id: str, zip_path: Path) -> Path:
        """Extracts a ZIP file safely into the workspace."""
        workspace_dir = WorkspaceManager.get_workspace_path(project_id)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                # Prevent path traversal
                if member.startswith('/') or '..' in member:
                    raise HTTPException(status_code=400, detail="Invalid zip file structure")
            zip_ref.extractall(workspace_dir)
            
        return workspace_dir

    @staticmethod
    def create_zip_from_workspace(project_id: str, output_path: Path):
        """Creates a ZIP file from the current workspace."""
        workspace_dir = WorkspaceManager.get_workspace_path(project_id)
        
        if not workspace_dir.exists():
            raise HTTPException(status_code=404, detail="Workspace not found")
            
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(workspace_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, workspace_dir)
                    zipf.write(file_path, arcname)
                    
        return output_path
