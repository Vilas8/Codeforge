import os
import re
from pathlib import Path

from app.projects.workspace import WorkspaceManager
from app.services.indexer import WorkspaceIndexService


MAX_CONTEXT_CHARS = 45000
MAX_FILE_CHARS = 16000
DEFAULT_RETRIEVAL_FILES = 12
IGNORED_DIRS = {".git", ".codeforge", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")


class WorkspaceContextService:
    @staticmethod
    def _safe_path(workspace: Path, relative: str) -> Path:
        target = (workspace / relative).resolve()
        target.relative_to(workspace.resolve())
        return target

    @staticmethod
    def _iter_files(workspace: Path):
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for filename in sorted(files):
                if filename.startswith("."):
                    continue
                path = Path(root) / filename
                if path.is_file() and path.stat().st_size <= MAX_FILE_CHARS:
                    yield path

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _score(path: Path, text: str, query: str) -> float:
        if not query.strip():
            return 0.0
        tokens = [t.lower() for t in TOKEN_RE.findall(query) if len(t) > 1]
        if not tokens:
            return 0.0
        rel = str(path).replace("\\", "/").lower()
        lower = text.lower()
        score = 0.0
        for token in tokens:
            if token in rel:
                score += 6.0
            occurrences = lower.count(token)
            score += min(occurrences, 8) * 1.0
        if path.name.lower() in {t.lower() for t in tokens}:
            score += 10.0
        return score

    @classmethod
    def search(cls, user_id: str, project_id: str, query: str, limit: int = DEFAULT_RETRIEVAL_FILES):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        try:
            indexed = WorkspaceIndexService.search(user_id, project_id, query, limit)
            if indexed:
                return [{
                    "path": item["path"], "score": item["score"],
                    "preview": item["content"][:1200],
                    "chunk_start": item["chunk_start"], "chunk_end": item["chunk_end"],
                    "source": "persistent_index",
                } for item in indexed]
        except Exception:
            pass

        scored = []
        for path in cls._iter_files(workspace):
            text = cls._read(path)
            if not text:
                continue
            score = cls._score(path, text, query)
            if score <= 0:
                continue
            rel = str(path.relative_to(workspace)).replace("\\", "/")
            scored.append({
                "path": rel, "score": round(score, 2),
                "preview": text[:1200], "source": "live_scan",
            })
        scored.sort(key=lambda item: (-item["score"], item["path"]))
        return scored[: max(1, min(limit, 30))]

    @classmethod
    def build(
        cls,
        user_id: str,
        project_id: str,
        directives: list[str] | None = None,
        selection: dict | None = None,
        query: str = "",
    ):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        directives = directives or ["@workspace"]
        result = {
            "directives": directives,
            "files": [],
            "selection": selection or None,
            "retrieval": "lexical" if query.strip() else "bounded",
        }
        chunks = []
        seen = set()
        total_chars = 0

        def add_file(path: Path):
            nonlocal total_chars
            try:
                rel = str(path.relative_to(workspace)).replace("\\", "/")
            except ValueError:
                return
            if rel in seen or total_chars >= MAX_CONTEXT_CHARS:
                return
            seen.add(rel)
            try:
                if path.is_file() and path.stat().st_size <= MAX_FILE_CHARS:
                    text = cls._read(path)
                    if not text:
                        return
                    piece = f"\n--- {rel} ---\n{text[:MAX_FILE_CHARS]}"
                    remaining = MAX_CONTEXT_CHARS - total_chars
                    piece = piece[:remaining]
                    chunks.append(piece)
                    total_chars += len(piece)
                    result["files"].append(rel)
            except OSError:
                pass

        for directive in directives:
            if directive == "@workspace":
                if query.strip():
                    ranked = cls.search(user_id, project_id, query, DEFAULT_RETRIEVAL_FILES)
                    for item in ranked:
                        add_file(workspace / item["path"])
                else:
                    for path in cls._iter_files(workspace):
                        add_file(path)
                        if total_chars >= MAX_CONTEXT_CHARS:
                            break
            elif directive.startswith("@file:"):
                try:
                    add_file(cls._safe_path(workspace, directive[6:].strip()))
                except (ValueError, OSError):
                    continue
            elif directive.startswith("@folder:"):
                try:
                    folder = cls._safe_path(workspace, directive[8:].strip())
                    for root, dirs, files in os.walk(folder):
                        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                        for filename in sorted(files):
                            add_file(Path(root) / filename)
                            if total_chars >= MAX_CONTEXT_CHARS:
                                break
                except (ValueError, OSError):
                    continue

        result["text"] = "".join(chunks)[:MAX_CONTEXT_CHARS]
        result["truncated"] = total_chars > MAX_CONTEXT_CHARS
        return result
