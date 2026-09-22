import json
import asyncio
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.core.security import get_current_user
from app.services.agent import CodeForgeAgent
from app.services.project_lock import ProjectAgentLock, ProjectBusyError
from app.ai.client import get_model
from app.projects.workspace import WorkspaceManager
from app.database.repositories.projects import ProjectRepository
from app.database.repositories.conversations import ConversationRepository

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    mode: str = "build"
    model: str = "default"
    context: dict = {}


@router.post("/{project_id}/chat")
async def chat_with_agent(project_id: str, req: ChatRequest, request: Request, user=Depends(get_current_user)):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        await asyncio.to_thread(
            ConversationRepository.add_message,
            user.id,
            project_id,
            "user",
            req.message,
            req.model if req.model not in {"", "default"} else None,
            {"mode": req.mode},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not save chat message: " + str(exc))

    workspace_dir = WorkspaceManager.get_workspace_path(user.id, project_id)
    lock = ProjectAgentLock(workspace_dir)
    try:
        lock.acquire()
    except ProjectBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    try:
        await asyncio.to_thread(
            WorkspaceManager.create_temporary_workspace,
            user.id,
            project_id,
        )

        mode = req.mode if req.mode in {"build", "review", "debug", "explain"} else "build"
        task = {"review": "review", "debug": "debug"}.get(mode, "coding")
        requested_model = (req.model or "").strip()
        model = get_model(task) if requested_model in {"", "default"} else requested_model

        async def event_generator():
            queue = asyncio.Queue()

            async def stream_callback(event):
                await queue.put(event)

            enriched_prompt = req.message
            if req.context:
                context_json = json.dumps(req.context, ensure_ascii=False)[:50000]
                enriched_prompt = f"{req.message}\n\nCODEFORGE WORKSPACE CONTEXT:\n{context_json}"

            agent = CodeForgeAgent(
                user.id,
                project_id,
                stream_callback=stream_callback,
                task=task,
                mode=mode,
                model=model,
            )
            agent_task = asyncio.create_task(agent.run(enriched_prompt))

            try:
                while True:
                    if await request.is_disconnected():
                        agent_task.cancel()
                        break

                    if agent_task.done() and queue.empty():
                        break

                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {json.dumps(event)}\\n\\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\\n\\n"

                if not agent_task.cancelled():
                    result = await agent_task

                    try:
                        await asyncio.to_thread(
                            WorkspaceManager.sync_workspace_to_storage,
                            user.id,
                            project_id,
                        )
                    except Exception as sync_exc:
                        yield f"data: {json.dumps({'type': 'error', 'stage': 'workspace_sync', 'message': 'Workspace sync failed: ' + str(sync_exc)})}\\n\\n"
                        return

                    if result:
                        try:
                            await asyncio.to_thread(
                                ConversationRepository.add_message,
                                user.id,
                                project_id,
                                "assistant",
                                result,
                                model,
                                {
                                    "mode": mode,
                                    "gateway": "freellmapi",
                                    "wire_api": agent.wire_api,
                                },
                            )
                        except Exception as persist_exc:
                            yield f"data: {json.dumps({'type': 'error', 'stage': 'conversation_persist', 'message': 'Chat response could not be saved: ' + str(persist_exc)})}\\n\\n"
                            return

                    yield f"data: {json.dumps({'type': 'done', 'message': result or 'Agent finished', 'model': model, 'gateway': 'freellmapi', 'wire_api': agent.wire_api})}\\n\\n"

            except asyncio.CancelledError:
                agent_task.cancel()
                raise
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'stage': 'agent', 'message': str(exc)})}\\n\\n"
            finally:
                if not agent_task.done():
                    agent_task.cancel()
                    try:
                        await agent_task
                    except asyncio.CancelledError:
                        pass

                try:
                    try:
                        await asyncio.to_thread(
                            WorkspaceManager.sync_workspace_to_storage,
                            user.id,
                            project_id,
                        )
                    except Exception as sync_exc:
                        yield f"data: {json.dumps({'type': 'error', 'stage': 'workspace_sync', 'message': 'Workspace sync failed: ' + str(sync_exc)})}\\n\\n"
                finally:
                    lock.release()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception:
        lock.release()
        raise
