import os
from pathlib import Path
from app.projects.workspace import WorkspaceManager


MAX_CONTEXT_CHARS = 45000
MAX_FILE_CHARS = 16000


class WorkspaceContextService:
    @staticmethod
    def _safe_path(workspace: Path, relative: str) -> Path:
        target = (workspace / relative).resolve()
        target.relative_to(workspace.resolve())
        return target

    @staticmethod
    def build(user_id: str, project_id: str, directives: list[str] | None = None, selection: dict | None = None):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        directives = directives or ["@workspace"]
        result = {"directives": directives, "files": [], "selection": selection or None}
        chunks = []
        seen = set()

        def add_file(path: Path):
            nonlocal chunks
            rel = str(path.relative_to(workspace)).replace("\\", "/")
            if rel in seen or len("".join(chunks)) >= MAX_CONTEXT_CHARS:
                return
            seen.add(rel)
            try:
                if path.is_file() and path.stat().st_size <= MAX_FILE_CHARS:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    chunks.append(f"\n--- {rel} ---\n{text[:MAX_FILE_CHARS]}")
                    result["files"].append(rel)
            except OSError:
                pass

        for directive in directives:
            if directive == "@workspace":
                for root, dirs, files in os.walk(workspace):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__"}]
                    for filename in sorted(files):
                        if filename.startswith("."):
                            continue
                        add_file(Path(root) / filename)
                        if len("".join(chunks)) >= MAX_CONTEXT_CHARS:
                            break
                    if len("".join(chunks)) >= MAX_CONTEXT_CHARS:
                        break
            elif directive.startswith("@file:"):
                try:
                    add_file(WorkspaceContextService._safe_path(workspace, directive[6:].strip()))
                except (ValueError, OSError):
                    continue
            elif directive.startswith("@folder:"):
                try:
                    folder = WorkspaceContextService._safe_path(workspace, directive[8:].strip())
                    for root, dirs, files in os.walk(folder):
                        dirs[:] = [d for d in dirs if not d.startswith(".")]
                        for filename in sorted(files):
                            add_file(Path(root) / filename)
                            if len("".join(chunks)) >= MAX_CONTEXT_CHARS:
                                break
                except (ValueError, OSError):
                    continue

        result["text"] = "".join(chunks)[:MAX_CONTEXT_CHARS]
        result["truncated"] = len("".join(chunks)) > MAX_CONTEXT_CHARS
        return result
