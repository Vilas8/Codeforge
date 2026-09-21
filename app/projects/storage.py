import os
from fastapi import UploadFile
from app.database.client import supabase

class SupabaseProjectStorage:
    BUCKET = "projects"

    @staticmethod
    def upload_file(storage_path: str, file_bytes: bytes, content_type: str = "text/plain"):
        """Uploads a file to Supabase Storage."""
        # Using upsert to overwrite if exists
        res = supabase.storage.from_(SupabaseProjectStorage.BUCKET).upload(
            file=file_bytes,
            path=storage_path,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return res

    @staticmethod
    def download_file(storage_path: str) -> bytes:
        """Downloads a file from Supabase Storage."""
        return supabase.storage.from_(SupabaseProjectStorage.BUCKET).download(storage_path)

    @staticmethod
    def delete_file(storage_path: str):
        """Deletes a file from Supabase Storage."""
        return supabase.storage.from_(SupabaseProjectStorage.BUCKET).remove([storage_path])

    @staticmethod
    def list_files(prefix: str):
        """Lists files in a specific project directory."""
        return supabase.storage.from_(SupabaseProjectStorage.BUCKET).list(prefix)
