import asyncio
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
        safe = message.replace("\\", " ").replace('"', "'").replace("\n", " ").strip()
        if not safe:
            return {"success": False, "code": -1, "output": "", "error": "Commit message is required."}
        return await GitService.run(workspace, f'git add -A && git commit -m "{safe[:200]}"')
