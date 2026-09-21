import json
import os
import shutil
import time
from pathlib import Path

LOCK_DIR_NAME = ".codeforge-agent.lock"
STALE_AFTER_SECONDS = 2 * 60 * 60

class ProjectBusyError(RuntimeError):
    pass

class ProjectAgentLock:
    """Atomic per-project lock for agent execution on a CodeForge instance."""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir.resolve()
        self.lock_dir = self.workspace_dir / LOCK_DIR_NAME
        self.acquired = False

    def acquire(self):
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.lock_dir.mkdir()
        except FileExistsError:
            if self._is_stale():
                shutil.rmtree(self.lock_dir, ignore_errors=True)
                try:
                    self.lock_dir.mkdir()
                except FileExistsError:
                    raise ProjectBusyError("Another agent is already working on this project.")
            else:
                raise ProjectBusyError("Another agent is already working on this project.")

        metadata = {"pid": os.getpid(), "created_at": time.time()}
        try:
            (self.lock_dir / "owner.json").write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )
        except OSError:
            shutil.rmtree(self.lock_dir, ignore_errors=True)
            raise

        self.acquired = True
        return self

    def release(self):
        if not self.acquired:
            return
        shutil.rmtree(self.lock_dir, ignore_errors=True)
        self.acquired = False

    def _is_stale(self):
        try:
            return time.time() - self.lock_dir.stat().st_mtime > STALE_AFTER_SECONDS
        except FileNotFoundError:
            return False
