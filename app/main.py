from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
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

cors_origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
if not cors_origins:
    cors_origins = ["http://localhost:8000", "http://127.0.0.1:8000"]
trusted_hosts = [item.strip() for item in settings.trusted_hosts.split(",") if item.strip()]
if trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > settings.request_max_body_mb * 1024 * 1024:
                        return JSONResponse({"detail": "Request body is too large."}, status_code=413)
                except ValueError:
                    return JSONResponse({"detail": "Invalid request content length."}, status_code=400)
        return await call_next(request)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "Universal CodeForge", "environment": settings.app_env}

@app.get("/api/readiness")
async def readiness_check():
    checks = {"configuration": "ok", "supabase": "unknown"}
    try:
        from app.database.client import supabase
        import asyncio
        await asyncio.to_thread(lambda: supabase.table("projects").select("id").limit(1).execute())
        checks["supabase"] = "ok"
    except Exception:
        checks["supabase"] = "error"
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )

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

