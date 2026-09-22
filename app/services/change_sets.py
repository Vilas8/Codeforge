import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.projects.storage import SupabaseProjectStorage
from app.projects.workspace import WorkspaceManager
from app.services.checkpoints import WorkspaceCheckpointService


class ChangeSetError(RuntimeError):
    pass


class WorkspaceChangeSetService:
    PREFIX = ".codeforge/change-sets"
    MAX_MANIFESTS = 50
    MAX_CONTENT_CHARS = 24000

    @classmethod
    def _prefix(cls, user_id: str, project_id: str, change_set_id: str) -> str:
        return f"{user_id}/{project_id}/{cls.PREFIX}/{change_set_id}"

    @classmethod
    def _manifest_path(cls, user_id: str, project_id: str, change_set_id: str) -> str:
        return f"{cls._prefix(user_id, project_id, change_set_id)}/manifest.json"

    @classmethod
    def create(
        cls,
        user_id: str,
        project_id: str,
        checkpoint_id: str | None,
        changes: list[dict],
        status: str = "pending_review",
    ):
        change_set_id = str(uuid.uuid4())
        normalized = []
        for change in changes:
            path = str(change.get("path", "")).strip()
            if not path:
                continue
            normalized.append({
                "path": path,
                "operation": change.get("operation", "write"),
                "created": bool(change.get("created", False)),
                "before": str(change.get("before", ""))[:cls.MAX_CONTENT_CHARS],
                "after": str(change.get("after", ""))[:cls.MAX_CONTENT_CHARS],
                "before_truncated": len(str(change.get("before", ""))) > cls.MAX_CONTENT_CHARS,
                "after_truncated": len(str(change.get("after", ""))) > cls.MAX_CONTENT_CHARS,
                "status": "pending",
            })

        manifest = {
            "id": change_set_id,
            "project_id": project_id,
            "checkpoint_id": checkpoint_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "file_count": len(normalized),
            "files": normalized,
        }
        SupabaseProjectStorage.upload_file(
            cls._manifest_path(user_id, project_id, change_set_id),
            json.dumps(manifest, indent=2).encode(),
            "application/json",
        )
        return manifest

    @classmethod
    def get(cls, user_id: str, project_id: str, change_set_id: str):
        try:
            raw = SupabaseProjectStorage.download_file(
                cls._manifest_path(user_id, project_id, change_set_id)
            )
            return json.loads(raw)
        except Exception as exc:
            raise ChangeSetError("Change set not found.") from exc

    @classmethod
    def _save(cls, user_id: str, project_id: str, manifest: dict):
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        SupabaseProjectStorage.upload_file(
            cls._manifest_path(user_id, project_id, manifest["id"]),
            json.dumps(manifest, indent=2).encode(),
            "application/json",
        )
        return manifest

    @classmethod
    def list(cls, user_id: str, project_id: str, limit: int = 20):
        prefix = f"{user_id}/{project_id}/{cls.PREFIX}"
        entries = SupabaseProjectStorage.list_files(prefix)
        manifests = []
        for entry in entries:
            name = entry.get("name", "")
            if not name.endswith("/manifest.json"):
                continue
            try:
                manifest = json.loads(
                    SupabaseProjectStorage.download_file(f"{prefix}/{name}")
                )
                manifests.append(manifest)
            except Exception:
                continue
        manifests.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return manifests[: max(1, min(limit, cls.MAX_MANIFESTS))]

    @classmethod
    def accept(cls, user_id: str, project_id: str, change_set_id: str):
        manifest = cls.get(user_id, project_id, change_set_id)
        for item in manifest.get("files", []):
            item["status"] = "accepted"
        manifest["status"] = "accepted"
        return cls._save(user_id, project_id, manifest)

    @classmethod
    def reject_all(cls, user_id: str, project_id: str, change_set_id: str):
        manifest = cls.get(user_id, project_id, change_set_id)
        checkpoint_id = manifest.get("checkpoint_id")
        if not checkpoint_id:
            raise ChangeSetError("This change set has no rollback checkpoint.")
        WorkspaceCheckpointService.restore(user_id, project_id, checkpoint_id)
        WorkspaceManager.sync_workspace_to_storage(user_id, project_id)
        for item in manifest.get("files", []):
            item["status"] = "rejected"
        manifest["status"] = "rejected"
        return cls._save(user_id, project_id, manifest)

    @classmethod
    def reject_file(cls, user_id: str, project_id: str, change_set_id: str, path: str):
        manifest = cls.get(user_id, project_id, change_set_id)
        target_item = next((x for x in manifest.get("files", []) if x.get("path") == path), None)
        if not target_item:
            raise ChangeSetError("File is not part of this change set.")
        checkpoint_id = manifest.get("checkpoint_id")
        if not checkpoint_id:
            raise ChangeSetError("This change set has no rollback checkpoint.")

        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        checkpoint_prefix = (
            f"{user_id}/{project_id}/{WorkspaceCheckpointService.PREFIX}/{checkpoint_id}"
        )
        checkpoint_manifest = WorkspaceCheckpointService.get_manifest(
            user_id, project_id, checkpoint_id
        )
        checkpoint_paths = {item["path"] for item in checkpoint_manifest.get("files", [])}

        target = (workspace / path).resolve()
        target.relative_to(workspace.resolve())
        if path in checkpoint_paths:
            data = SupabaseProjectStorage.download_file(f"{checkpoint_prefix}/{path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        elif target.exists():
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                raise ChangeSetError("Refusing to delete a directory during file rollback.")

        target_item["status"] = "rejected"
        if all(x.get("status") == "rejected" for x in manifest.get("files", [])):
            manifest["status"] = "rejected"
        elif all(x.get("status") in {"accepted", "rejected"} for x in manifest.get("files", [])):
            manifest["status"] = "partially_resolved"
        WorkspaceManager.sync_workspace_to_storage(user_id, project_id)
        return cls._save(user_id, project_id, manifest)
