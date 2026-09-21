from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user
from app.projects.workspace import WorkspaceManager
import os

router = APIRouter()

class FileUpdate(BaseModel):
    path: str
    content: str

@router.get("/{project_id}/tree")
async def get_project_tree(project_id: str, user=Depends(get_current_user)):
    """Returns the file tree for the UI."""
    workspace_dir = WorkspaceManager.get_workspace_path(project_id)
    if not workspace_dir.exists():
        # Sync if not exists
        WorkspaceManager.create_temporary_workspace(user.id, project_id)
        
    tree = []
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), workspace_dir)
            tree.append(rel_path.replace('\\', '/'))
    return {"files": sorted(tree)}

@router.get("/{project_id}/file")
async def get_file_content(project_id: str, path: str, user=Depends(get_current_user)):
    workspace_dir = WorkspaceManager.get_workspace_path(project_id)
    target = (workspace_dir / path).resolve()
    
    if not str(target).startswith(str(workspace_dir)) or not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    with open(target, 'r', encoding='utf-8') as f:
        return {"content": f.read()}

@router.put("/{project_id}/file")
async def update_file(project_id: str, file_data: FileUpdate, user=Depends(get_current_user)):
    workspace_dir = WorkspaceManager.get_workspace_path(project_id)
    target = (workspace_dir / file_data.path).resolve()
    
    if not str(target).startswith(str(workspace_dir)):
        raise HTTPException(status_code=403, detail="Invalid path")
        
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        f.write(file_data.content)
        
    # Sync immediately on manual UI save
    WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
    return {"status": "success"}
