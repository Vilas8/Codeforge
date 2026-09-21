import json
import asyncio
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.core.security import get_current_user
from app.services.agent import CodeForgeAgent
from app.services.project_lock import ProjectAgentLock, ProjectBusyError
from app.ai.client import get_model, get_provider_for_model
from app.projects.workspace import WorkspaceManager
from app.database.repositories.projects import ProjectRepository

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    mode: str = "build"
    model: str = "default"

@router.post("/{project_id}/chat")
async def chat_with_agent(project_id: str, req: ChatRequest, request: Request, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    lock = ProjectAgentLock(workspace_dir)
    try:
        lock.acquire()
    except ProjectBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    try:
        WorkspaceManager.create_temporary_workspace(user.id, project_id)

        mode = req.mode if req.mode in {"build", "review", "debug", "explain"} else "build"
        task = {"review": "review", "debug": "debug"}.get(mode, "coding")
        requested_model = (req.model or "").strip()
        model = get_model(task) if requested_model in {"", "default"} else requested_model
        try:
            provider = get_provider_for_model(model)
        except ValueError as exc:
            lock.release()
            raise HTTPException(status_code=400, detail=str(exc))

        async def event_generator():
            queue = asyncio.Queue()

            async def stream_callback(event):
                await queue.put(event)

            agent = CodeForgeAgent(
                user.id,
                project_id,
                stream_callback=stream_callback,
                task=task,
                mode=mode,
                model=model,
            )
            agent_task = asyncio.create_task(agent.run(req.message))
            try:
                while True:
                    if await request.is_disconnected():
                        agent_task.cancel()
                        break
                    if agent_task.done() and queue.empty():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        continue

                if not agent_task.cancelled():
                    result = await agent_task
                    WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
                    yield f"data: {json.dumps({'type': 'done', 'message': result or 'Agent finished', 'model': model, 'provider': provider})}\n\n"
            except asyncio.CancelledError:
                agent_task.cancel()
                raise
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            finally:
                if not agent_task.done():
                    agent_task.cancel()
                    try:
                        await agent_task
                    except asyncio.CancelledError:
                        pass
                try:
                    try:
                        WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
                    except Exception as sync_exc:
                        yield f"data: {json.dumps({'type': 'error', 'message': 'Workspace sync failed: ' + str(sync_exc)})}\n\n"
                finally:
                    lock.release()

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    except Exception:
        lock.release()
        raise
