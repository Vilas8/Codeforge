import asyncio
import shlex
from app.services.executor import CommandExecutor

class GitService:
    @staticmethod
    async def run(workspace, command):
        result = await CommandExecutor.run(workspace, command, 30)
        return {
            "success": result["success"],
            "code": result["code"],
            "output": result["output"],
            "error": result["error"],
        }

    @staticmethod
    async def status(workspace):
        return await GitService.run(workspace, "git status --short --branch")

    @staticmethod
    async def diff(workspace):
        return await GitService.run(workspace, "git diff --no-ext-diff -- .")

    @staticmethod
    async def log(workspace):
        return await GitService.run(workspace, "git log -10 --oneline --decorate")

    @staticmethod
    async def commit(workspace, message):
        safe = str(message).replace("\r", " ").replace("\n", " ").strip()[:200]
        if not safe:
            return {"success": False, "code": -1, "output": "", "error": "Commit message is required."}
        quoted_message = shlex.quote(safe)
        return await GitService.run(workspace, f"git add -A && git commit -m {quoted_message}")
