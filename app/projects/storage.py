import os
import threading
from fastapi import UploadFile
from app.database.client import supabase

class SupabaseProjectStorage:
    BUCKET = "projects"
    _bucket_lock = threading.Lock()
    _bucket_ready = False

    @classmethod
    def ensure_bucket(cls):
        """Ensure the private project bucket exists before using Storage."""
        if cls._bucket_ready:
            return
        with cls._bucket_lock:
            if cls._bucket_ready:
                return
            try:
                supabase.storage.get_bucket(cls.BUCKET)
            except Exception:
                # The backend uses the service-role client, so it can
                # provision the application's private bucket on first use.
                try:
                    supabase.storage.create_bucket(
                        cls.BUCKET,
                        options={"public": False},
                    )
                except Exception as create_exc:
                    # Another request may have created it between get/create.
                    try:
                        supabase.storage.get_bucket(cls.BUCKET)
                    except Exception:
                        raise RuntimeError(
                            f"Supabase Storage bucket '{cls.BUCKET}' is unavailable: {create_exc}"
                        ) from create_exc
            cls._bucket_ready = True

    @classmethod
    def upload_file(storage_path: str, file_bytes: bytes, content_type: str = "text/plain"):
        """Uploads a file to Supabase Storage."""
        cls.ensure_bucket()
        # Using upsert to overwrite if exists
        res = supabase.storage.from_(cls.BUCKET).upload(
            file=file_bytes,
            path=storage_path,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return res

    @staticmethod
    def download_file(storage_path: str) -> bytes:
        """Downloads a file from Supabase Storage."""
        SupabaseProjectStorage.ensure_bucket()
        return supabase.storage.from_(SupabaseProjectStorage.BUCKET).download(storage_path)

    @staticmethod
    def delete_file(storage_path: str):
        """Deletes a file from Supabase Storage."""
        SupabaseProjectStorage.ensure_bucket()
        return supabase.storage.from_(SupabaseProjectStorage.BUCKET).remove([storage_path])

    @staticmethod
    def delete_files(storage_paths: list[str]):
        """Deletes multiple files from Supabase Storage."""
        if not storage_paths:
            return None
        SupabaseProjectStorage.ensure_bucket()
        return supabase.storage.from_(SupabaseProjectStorage.BUCKET).remove(storage_paths)

    @staticmethod
    def list_files(prefix: str):
        """Recursively lists files below a storage prefix."""
        SupabaseProjectStorage.ensure_bucket()
        bucket = supabase.storage.from_(SupabaseProjectStorage.BUCKET)
        results = []

        def walk(current_prefix: str, relative_prefix: str = ""):
            entries = bucket.list(current_prefix) or []
            for entry in entries:
                name = entry.get("name", "")
                if not name or name == ".emptyFolderPlaceholder":
                    continue
                relative_name = f"{relative_prefix}/{name}".strip("/")
                metadata = entry.get("metadata")
                entry_id = entry.get("id")
                if entry_id is None and metadata is None:
                    walk(f"{current_prefix}/{name}", relative_name)
                else:
                    results.append({**entry, "name": relative_name})

        walk(prefix.rstrip("/"))
        return results
