from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.security import get_current_user
from app.projects.workspace import WorkspaceManager
from app.services.context import WorkspaceContextService
from app.services.checkpoints import WorkspaceCheckpointService
from app.database.repositories.projects import ProjectRepository
from app.ai.client import get_ai_client, get_model

router = APIRouter()


class ContextRequest(BaseModel):
    directives: list[str] = Field(default_factory=lambda: ["@workspace"])
    selection: dict | None = None
    query: str = ""


class InlineEditRequest(BaseModel):
    path: str
    selection: str
    instruction: str
    model: str = "default"


class CheckpointRequest(BaseModel):
    action: str = "create"
    checkpoint_id: str | None = None


def _project_or_404(user, project_id):
    if not ProjectRepository.get_by_id(user.id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/context")
async def workspace_context(project_id: str, req: ContextRequest, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    return WorkspaceContextService.build(user.id, project_id, req.directives, req.selection, req.query)


@router.get("/{project_id}/search")
async def search_workspace(project_id: str, q: str = "", limit: int = 12, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    return {"query": q, "results": WorkspaceContextService.search(user.id, project_id, q, limit)}


@router.post("/{project_id}/checkpoint")
async def checkpoint(project_id: str, req: CheckpointRequest, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    if req.action == "create":
        return {"action": "created", "checkpoint": WorkspaceCheckpointService.create(user.id, project_id)}
    if req.action == "restore" and req.checkpoint_id:
        manifest = WorkspaceCheckpointService.restore(user.id, project_id, req.checkpoint_id)
        WorkspaceManager.sync_workspace_to_storage(user.id, project_id)
        return {"action": "restored", "checkpoint": manifest}
    raise HTTPException(status_code=400, detail="Use action=create or action=restore with checkpoint_id")

@router.post("/{project_id}/inline-edit")
async def inline_edit(project_id: str, req: InlineEditRequest, user=Depends(get_current_user)):
    _project_or_404(user, project_id)
    WorkspaceManager.create_temporary_workspace(user.id, project_id)
    workspace = WorkspaceManager.get_workspace_path(user.id, project_id)
    target = WorkspaceContextService._safe_path(workspace, req.path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    model = req.model if req.model not in {"", "default"} else get_model("coding")
    prompt = (
        "You are editing " + req.path + " in CodeForge.\n"
        "Instruction: " + req.instruction + "\n\n"
        "Return ONLY the replacement code for the selected region. "
        "Do not use Markdown fences. Preserve surrounding code assumptions.\n\n"
        "Selected code:\n" + req.selection[:30000]
    )
    client = get_ai_client()
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a precise inline code editor. Return only code."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    content = response.choices[0].message.content or ""
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            content = "\n".join(lines[1:-1])
    return {"path": req.path, "replacement": content, "model": model}
