import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.projects.workspace import WorkspaceManager
from app.database.client import supabase

TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]{2,}")
IGNORED_DIRS = {".git", ".codeforge", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
MAX_FILE_BYTES = 200000
MAX_CHUNKS_PER_FILE = 80
CHUNK_CHARS = 1800


class WorkspaceIndexService:
    """Persistent bounded code index used for fast workspace retrieval."""

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return list(dict.fromkeys(t.lower() for t in TOKEN_RE.findall(text)))

    @staticmethod
    def _chunks(path: str, text: str):
        lines = text.splitlines()
        chunks = []
        current, start = [], 1
        for number, line in enumerate(lines, 1):
            current.append(line)
            if sum(len(x) + 1 for x in current) >= CHUNK_CHARS:
                chunks.append((start, number, "\n".join(current)))
                current, start = [], number + 1
                if len(chunks) >= MAX_CHUNKS_PER_FILE:
                    break
        if current and len(chunks) < MAX_CHUNKS_PER_FILE:
            chunks.append((start, len(lines), "\n".join(current)))
        return chunks

    @classmethod
    def build(cls, user_id: str, project_id: str):
        workspace = WorkspaceManager.get_workspace_path(user_id, project_id)
        rows = []
        file_count = 0
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for filename in files:
                path = Path(root) / filename
                if filename.startswith(".") or path.stat().st_size > MAX_FILE_BYTES:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                relative = str(path.relative_to(workspace)).replace("\\", "/")
                digest = hashlib.sha256(text.encode()).hexdigest()
                for start, end, chunk in cls._chunks(relative, text):
                    rows.append({
                        "user_id": user_id,
                        "project_id": project_id,
                        "path": relative,
                        "chunk_start": start,
                        "chunk_end": end,
                        "content": chunk,
                        "tokens": cls._tokens(relative + "\n" + chunk),
                        "content_hash": digest,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                file_count += 1

        supabase.table("workspace_index").delete().eq("user_id", user_id).eq("project_id", project_id).execute()
        for offset in range(0, len(rows), 100):
            supabase.table("workspace_index").insert(rows[offset:offset + 100]).execute()
        return {"files": file_count, "chunks": len(rows), "indexed_at": datetime.now(timezone.utc).isoformat()}

    @classmethod
    def search(cls, user_id: str, project_id: str, query: str, limit: int = 12):
        tokens = cls._tokens(query)
        if not tokens:
            return []
        response = supabase.table("workspace_index").select("path,chunk_start,chunk_end,content").eq("user_id", user_id).eq("project_id", project_id).limit(1000).execute()
        scored = []
        for row in response.data or []:
            haystack = (row["path"] + "\n" + row["content"]).lower()
            score = sum(min(haystack.count(token), 8) for token in tokens)
            score += sum(4 for token in tokens if token in row["path"].lower())
            if score:
                item = dict(row)
                item["score"] = score
                scored.append(item)
        scored.sort(key=lambda x: (-x["score"], x["path"], x["chunk_start"]))
        return scored[:max(1, min(limit, 50))]
