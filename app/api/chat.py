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
from app.services.checkpoints import WorkspaceCheckpointService
from app.services.audit import AuditService
from app.services.change_sets import WorkspaceChangeSetService
from app.services.orchestrator import AgentOrchestrator
from app.services.agent_runs import AgentRunService
from app.services.indexer import WorkspaceIndexService

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    mode: str = "build"
    model: str = "default"
    context: dict = {}
    workflow: str = "standard"


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

        AuditService.record(user.id, project_id, "agent.start", "success", {"mode": req.mode, "model": req.model})
        mode = req.mode if req.mode in {"plan", "build", "debug", "review", "test", "refactor", "security", "optimize", "explain"} else "build"
        task = {"plan": "planning", "review": "review", "debug": "debug", "security": "review"}.get(mode, "coding")
        requested_model = (req.model or "").strip()
        model = get_model(task) if requested_model in {"", "default"} else requested_model
        checkpoint = None
        if mode in {"build", "debug", "refactor", "optimize"}:
            try:
                checkpoint = WorkspaceCheckpointService.create(user.id, project_id)
            except Exception:
                checkpoint = None

        async def event_generator():
            queue = asyncio.Queue()
            changes = []
            if checkpoint:
                await queue.put({"type": "checkpoint", "checkpoint_id": checkpoint["id"], "file_count": checkpoint["file_count"]})

            async def stream_callback(event):
                if event.get("type") == "file_change":
                    changes.append(event)
                await queue.put(event)

            enriched_prompt = req.message
            if req.context:
                context_json = json.dumps(req.context, ensure_ascii=False)[:50000]
                enriched_prompt = f"{req.message}\n\nCODEFORGE WORKSPACE CONTEXT:\n{context_json}"

            runner = None
            agent = None
            orchestrator = None
            run_record = None
            try:
                run_record = await asyncio.to_thread(AgentRunService.start, user.id, project_id, mode, req.workflow, model)
            except Exception:
                run_record = None

            async def run_agent():
                nonlocal runner, agent, orchestrator
                if req.workflow == "autopilot":
                    orchestrator = AgentOrchestrator(
                        user.id, project_id, stream_callback=stream_callback, model=model
                    )
                    runner = orchestrator
                    return await orchestrator.run(enriched_prompt)
                agent = CodeForgeAgent(
                    user.id, project_id, stream_callback=stream_callback,
                    task=task, mode=mode, model=model
                )
                runner = agent
                return await agent.run(enriched_prompt)

            agent_task = asyncio.create_task(run_agent())

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

                    if changes and checkpoint:
                        change_set = await asyncio.to_thread(
                            WorkspaceChangeSetService.create, user.id, project_id,
                            checkpoint["id"], changes, "pending_review"
                        )
                        yield "data: " + json.dumps({"type": "change_set", "change_set_id": change_set["id"], "file_count": change_set["file_count"], "status": change_set["status"]}) + "\\n\\n"

                    try:
                        await asyncio.to_thread(
                            WorkspaceManager.sync_workspace_to_storage,
                            user.id,
                            project_id,
                        )
                        if req.workflow == "autopilot" or changes:
                            await asyncio.to_thread(WorkspaceIndexService.build, user.id, project_id)
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
                                    "wire_api": getattr(agent, "wire_api", "mixed") if agent else "mixed",
                                },
                            )
                        except Exception as persist_exc:
                            yield f"data: {json.dumps({'type': 'error', 'stage': 'conversation_persist', 'message': 'Chat response could not be saved: ' + str(persist_exc)})}\\n\\n"
                            return

                    yield f"data: {json.dumps({'type': 'done', 'message': result or 'Agent finished', 'model': model, 'gateway': 'freellmapi', 'wire_api': (getattr(agent, 'wire_api', 'mixed') if agent else 'mixed')})}\\n\\n"
                    tool_calls = getattr(runner, "total_tool_calls", None)
                    if tool_calls is None:
                        tool_calls = getattr(runner, "tool_calls", 0)
                    file_changes = getattr(runner, "total_file_changes", None)
                    if file_changes is None:
                        file_changes = getattr(runner, "file_changes", 0)
                    AuditService.record(user.id, project_id, "agent.complete", "success", {
                        "mode": mode, "workflow": req.workflow, "model": model,
                        "tool_calls": tool_calls, "file_changes": file_changes
                    })
                    if run_record:
                        await asyncio.to_thread(
                            AgentRunService.finish, run_record["id"], "completed",
                            {"tool_calls": tool_calls, "file_changes": file_changes, "change_set_id": change_set["id"] if change_set else None}
                        )

            except asyncio.CancelledError:
                agent_task.cancel()
                raise
            except Exception as exc:
                if changes and checkpoint:
                    try:
                        failed_change_set = await asyncio.to_thread(
                            WorkspaceChangeSetService.create, user.id, project_id,
                            checkpoint["id"], changes, "error_pending_review"
                        )
                        yield "data: " + json.dumps({"type": "change_set", "change_set_id": failed_change_set["id"], "file_count": failed_change_set["file_count"], "status": failed_change_set["status"]}) + "\\n\\n"
                    except Exception:
                        pass
                tool_calls = getattr(runner, "total_tool_calls", 0) if runner else 0
                if tool_calls is None:
                    tool_calls = getattr(runner, "tool_calls", 0)
                file_changes = getattr(runner, "total_file_changes", 0) if runner else 0
                if file_changes is None:
                    file_changes = getattr(runner, "file_changes", 0)
                AuditService.record(user.id, project_id, "agent.complete", "error", {
                    "mode": mode, "workflow": req.workflow, "model": model,
                    "error": str(exc)[:500], "tool_calls": tool_calls, "file_changes": file_changes
                })
                if run_record:
                    await asyncio.to_thread(
                        AgentRunService.finish, run_record["id"], "error",
                        {"error": str(exc)[:500], "tool_calls": tool_calls, "file_changes": file_changes}
                    )
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
