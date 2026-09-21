import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.core.security import get_current_user
from app.services.agent import CodeForgeAgent
from app.projects.workspace import WorkspaceManager

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

@router.post("/{project_id}/chat")
async def chat_with_agent(project_id: str, req: ChatRequest, request: Request, user=Depends(get_current_user)):
    """
    Streams the agent's response and tool calls back to the client via SSE.
    """
    # 1. Ensure workspace is active/synced from Supabase
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    
    async def event_generator():
        queue = asyncio.Queue()
        
        async def stream_callback(event: dict):
            await queue.put(event)
            
        agent = CodeForgeAgent(project_id, stream_callback=stream_callback)
        
        # Run agent in background
        agent_task = asyncio.create_task(agent.run(req.message))
        
        while not agent_task.done() or not queue.empty():
            try:
                # Wait for next event with a tiny timeout to check task status
                event = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break
                
        # Get final result to ensure any exceptions are caught
        try:
            await agent_task
            # Sync back to Supabase
            WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
