from datetime import datetime, timezone
from app.database.client import supabase

class ConversationRepository:
    @staticmethod
    def get_or_create(user_id: str, project_id: str, title: str | None = None):
        result = (
            supabase.table("conversations")
            .select("*")
            .eq("user_id", user_id)
            .eq("project_id", project_id)
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )
        if result.data:
            conversation = result.data[0]
            if title and not conversation.get("title"):
                updated = supabase.table("conversations").update({
                    "title": title[:120],
                }).eq("id", conversation["id"]).execute()
                if updated.data:
                    conversation = updated.data[0]
            return conversation

        result = supabase.table("conversations").insert({
            "user_id": user_id,
            "project_id": project_id,
            "title": (title or "New chat")[:120],
        }).execute()
        return result.data[0] if result.data else None

    @staticmethod
    def add_message(user_id: str, project_id: str, role: str, content: str, model: str | None = None, metadata: dict | None = None):
        conversation = ConversationRepository.get_or_create(
            user_id,
            project_id,
            title=content.strip()[:80] if role == "user" else None,
        )
        if not conversation:
            raise RuntimeError("Could not create conversation.")
        result = supabase.table("messages").insert({
            "conversation_id": conversation["id"],
            "role": role,
            "content": content,
            "model": model,
            "metadata": metadata or {},
        }).execute()
        supabase.table("conversations").update({
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", conversation["id"]).execute()
        return result.data[0] if result.data else None

    @staticmethod
    def get_history(user_id: str, project_id: str):
        conversations = (
            supabase.table("conversations")
            .select("id,title,created_at,updated_at")
            .eq("user_id", user_id)
            .eq("project_id", project_id)
            .order("updated_at", desc=True)
            .execute()
        )
        if not conversations.data:
            return {"conversations": [], "messages": []}

        conversation_ids = [item["id"] for item in conversations.data]
        messages = (
            supabase.table("messages")
            .select("id,conversation_id,role,content,model,metadata,created_at")
            .in_("conversation_id", conversation_ids)
            .order("created_at", desc=False)
            .execute()
        )
        return {
            "conversations": conversations.data,
            "messages": messages.data or [],
        }
