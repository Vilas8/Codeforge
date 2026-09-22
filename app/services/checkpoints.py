import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app.projects.storage import SupabaseProjectStorage
from app.projects.workspace import WorkspaceManager


class WorkspaceCheckpointService:
    PREFIX = ".codeforge/checkpoints"

    @staticmethod
    def create(user_id: str, project_id: str):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        checkpoint_id = str(uuid.uuid4())
        prefix = f"{user_id}/{project_id}/{WorkspaceCheckpointService.PREFIX}/{checkpoint_id}"
        files = []
        for root, _, names in __import__("os").walk(workspace):
            for name in names:
                path = Path(root) / name
                rel = str(path.relative_to(workspace)).replace("\\", "/")
                data = path.read_bytes()
                SupabaseProjectStorage.upload_file(f"{prefix}/{rel}", data)
                files.append({"path": rel, "size": len(data)})
        manifest = {
            "id": checkpoint_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files),
            "files": files,
        }
        SupabaseProjectStorage.upload_file(
            f"{prefix}/manifest.json",
            json.dumps(manifest, indent=2).encode(),
            "application/json",
        )
        return manifest

    @staticmethod
    def restore(user_id: str, project_id: str, checkpoint_id: str):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        prefix = f"{user_id}/{project_id}/{WorkspaceCheckpointService.PREFIX}/{checkpoint_id}"
        manifest = json.loads(SupabaseProjectStorage.download_file(f"{prefix}/manifest.json"))
        for root, _, names in __import__("os").walk(workspace):
            for name in names:
                (Path(root) / name).unlink()
        for item in manifest.get("files", []):
            rel = item["path"]
            data = SupabaseProjectStorage.download_file(f"{prefix}/{rel}")
            target = (workspace / rel).resolve()
            target.relative_to(workspace.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return manifest
