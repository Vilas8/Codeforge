from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.database.repositories.projects import ProjectRepository
from app.database.repositories.conversations import ConversationRepository

router = APIRouter()

class MessageCreate(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str
    model: str | None = None
    metadata: dict | None = None

@router.get("/{project_id}/history")
async def get_history(project_id: str, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return ConversationRepository.get_history(user.id, project_id)

@router.post("/{project_id}/messages")
async def create_message(project_id: str, payload: MessageCreate, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    message = ConversationRepository.add_message(
        user.id,
        project_id,
        payload.role,
        payload.content,
        payload.model,
        payload.metadata,
    )
    if not message:
        raise HTTPException(status_code=500, detail="Could not save message")
    return message
