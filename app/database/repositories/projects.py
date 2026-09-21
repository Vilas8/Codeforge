from app.database.client import supabase


from app.projects.storage import SupabaseProjectStorage
from app.projects.workspace import WorkspaceManager

class ProjectRepository:
    @staticmethod
    def ensure_profile(user_id: str, email: str | None = None):
        profile = {"id": user_id}
        if email:
            profile["email"] = email
        try:
            existing = supabase.table("profiles").select("id,email").eq("id", user_id).limit(1).execute()
            if existing.data:
                return existing.data[0]
            if not email:
                raise ValueError("Authenticated user has no profile email.")
            result = supabase.table("profiles").insert(profile).execute()
            return result.data[0] if result.data else None
        except Exception:
            # A concurrent request may create the profile between SELECT and INSERT.
            existing = supabase.table("profiles").select("id,email").eq("id", user_id).limit(1).execute()
            if existing.data:
                return existing.data[0]
            raise

    @staticmethod
    def create(user_id: str, name: str, description: str, slug: str, email: str | None = None):
        ProjectRepository.ensure_profile(user_id, email)
        data = {
            "user_id": user_id,
            "name": name,
            "description": description,
            "slug": slug,
            "storage_path": f"projects/{user_id}/"
        }
        result = supabase.table("projects").insert(data).execute()
        # storage_path will be appended with project id after creation
        if result.data:
            project = result.data[0]
            project_id = project["id"]
            storage_path = f"projects/{user_id}/{project_id}"
            supabase.table("projects").update({"storage_path": storage_path}).eq("id", project_id).execute()
            project["storage_path"] = storage_path
            return project
        return None

    @staticmethod
    def get_all(user_id: str):
        result = supabase.table("projects").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
        return result.data

    @staticmethod
    def get_by_id(user_id: str, project_id: str):
        result = supabase.table("projects").select("*").eq("user_id", user_id).eq("id", project_id).execute()
        return result.data[0] if result.data else None

    @staticmethod
    def delete(user_id: str, project_id: str):
        prefix = f"{user_id}/{project_id}/files"
        remote_files = SupabaseProjectStorage.list_files(prefix)
        storage_paths = [
            f"{prefix}/{item['name']}"
            for item in remote_files
            if item.get("name") != ".emptyFolderPlaceholder"
        ]
        if storage_paths:
            SupabaseProjectStorage.delete_files(storage_paths)

        WorkspaceManager.cleanup_workspace(user_id, project_id)
        result = supabase.table("projects").delete().eq("user_id", user_id).eq("id", project_id).execute()
        return result.data
