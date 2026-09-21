from app.database.client import supabase

class ProjectRepository:
    @staticmethod
    def create(user_id: str, name: str, description: str, slug: str):
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
            project_id = project['id']
            storage_path = f"projects/{user_id}/{project_id}"
            supabase.table("projects").update({"storage_path": storage_path}).eq("id", project_id).execute()
            project['storage_path'] = storage_path
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
        result = supabase.table("projects").delete().eq("user_id", user_id).eq("id", project_id).execute()
        return result.data
