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
        with WorkspaceManager.workspace_lock(user_id, project_id):
            return WorkspaceCheckpointService._create_locked(user_id, project_id)

    @staticmethod
    def _create_locked(user_id: str, project_id: str):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        checkpoint_id = str(uuid.uuid4())
        prefix = f"{user_id}/{project_id}/{WorkspaceCheckpointService.PREFIX}/{checkpoint_id}"
        files = []
        for root, dirs, names in __import__("os").walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith(".codeforge")]
            for name in names:
                if name == ".codeforge-agent.lock":
                    continue
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
    def get_manifest(user_id: str, project_id: str, checkpoint_id: str):
        prefix = f"{user_id}/{project_id}/{WorkspaceCheckpointService.PREFIX}/{checkpoint_id}"
        return json.loads(
            SupabaseProjectStorage.download_file(f"{prefix}/manifest.json")
        )

    @staticmethod
    def restore(user_id: str, project_id: str, checkpoint_id: str):
        with WorkspaceManager.workspace_lock(user_id, project_id):
            return WorkspaceCheckpointService._restore_locked(user_id, project_id, checkpoint_id)

    @staticmethod
    def _restore_locked(user_id: str, project_id: str, checkpoint_id: str):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        prefix = f"{user_id}/{project_id}/{WorkspaceCheckpointService.PREFIX}/{checkpoint_id}"
        manifest = json.loads(SupabaseProjectStorage.download_file(f"{prefix}/manifest.json"))
        for root, dirs, names in __import__("os").walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith(".codeforge")]
            for name in names:
                if name == ".codeforge-agent.lock":
                    continue
                (Path(root) / name).unlink()
        for item in manifest.get("files", []):
            try:
                rel = WorkspaceManager.normalize_relative_path(item["path"])
                target = WorkspaceManager.safe_path(user_id, project_id, rel)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid checkpoint file path.") from exc
            data = SupabaseProjectStorage.download_file(f"{prefix}/{rel}")
            if target.exists() and target.is_dir():
                raise ValueError("Checkpoint file conflicts with a directory.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        WorkspaceManager._sync_workspace_to_storage(user_id, project_id)
        return manifest
