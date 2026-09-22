from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings

from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.chat import router as chat_router
from app.api.files import router as files_router
from app.api.profile import router as profile_router
from app.api.conversations import router as conversations_router
from app.api.ai import router as ai_router
from app.api.context import router as context_router
from app.api.git import router as git_router
from app.api.audit import router as audit_router
from app.api.changes import router as changes_router
from app.api.index import router as index_router
from app.api.runs import router as runs_router
from app.api.memory import router as memory_router
from app.api.diagnostics import router as diagnostics_router
from app.api.jobs import router as jobs_router
from app.api.metrics import router as metrics_router

app = FastAPI(
    title="Universal CodeForge",
    description="AI Coding Agent Web Application",
    version="1.0.0"
)

from fastapi.responses import FileResponse

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    # The public landing page is static HTML. Serving it directly avoids
    # template parsing/runtime failures on the unauthenticated entry route.
    return FileResponse("templates/index.html", media_type="text/html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "Universal CodeForge", "environment": settings.app_env}

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(projects_router, prefix="/api/projects", tags=["Projects"])
app.include_router(chat_router, prefix="/api/agent", tags=["Agent"])
app.include_router(files_router, prefix="/api/workspace", tags=["Workspace"])
app.include_router(profile_router, prefix="/api/profile", tags=["Profile"])
app.include_router(conversations_router, prefix="/api/conversations", tags=["Conversations"])
app.include_router(ai_router, prefix="/api/ai", tags=["AI"])
app.include_router(context_router, prefix="/api/context", tags=["Context"])
app.include_router(git_router, prefix="/api/git", tags=["Git"])
app.include_router(audit_router, prefix="/api/audit", tags=["Audit"])
app.include_router(changes_router, prefix="/api/changes", tags=["Changes"])
app.include_router(index_router, prefix="/api/index", tags=["Index"])
app.include_router(runs_router, prefix="/api/runs", tags=["Runs"])
app.include_router(memory_router, prefix="/api/memory", tags=["Memory"])
app.include_router(diagnostics_router, prefix="/api/diagnostics", tags=["Diagnostics"])
app.include_router(jobs_router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(metrics_router, prefix="/api/metrics", tags=["Metrics"])

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

