import json
import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.core.security import get_current_user
from app.services.agent import CodeForgeAgent
from app.projects.workspace import WorkspaceManager

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    mode: str = "build"
    model: str = "default"

@router.post("/{project_id}/chat")
async def chat_with_agent(project_id: str, req: ChatRequest, request: Request, user=Depends(get_current_user)):
    """Streams the agent response, tool activity, and file changes over SSE."""
    WorkspaceManager.create_temporary_workspace(user.id, project_id)

    task_map = {
        "planning": "planning",
        "coding": "coding",
        "review": "review",
        "debug": "debug",
    }
    task = task_map.get(req.model, task_map.get(req.mode, "coding"))
    mode = req.mode if req.mode in {"build", "review", "debug", "explain"} else "build"

    async def event_generator():
        queue = asyncio.Queue()

        async def stream_callback(event: dict):
            await queue.put(event)

        agent = CodeForgeAgent(
            project_id,
            stream_callback=stream_callback,
            task=task,
            mode=mode,
        )
        agent_task = asyncio.create_task(agent.run(req.message))

        while not agent_task.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                break

        try:
            await agent_task
            WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
