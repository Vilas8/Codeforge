import asyncio
import os
import signal
from pathlib import Path
from app.core.config import settings

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
MAX_COMMAND_LENGTH = 12000
MAX_OUTPUT_BYTES = 100_000

SAFE_ENV_KEYS = {
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
    "SHELL", "TERM", "CI", "NODE_ENV", "PYTHONUNBUFFERED",
}

class CommandExecutor:
    """Run workspace commands with a production Docker sandbox by default."""

    @staticmethod
    def _safe_env(workspace_dir: Path) -> dict:
        env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
        env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
        env["CODEFORGE_WORKSPACE"] = str(workspace_dir)
        return env

    @staticmethod
    async def _run_process(workspace_dir: Path, command: str, timeout: int) -> dict:
        process = None
        try:
            process = await asyncio.create_subprocess_shell(
                command, cwd=str(workspace_dir), env=CommandExecutor._safe_env(workspace_dir),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name != "nt"),
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output = stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") if stdout else ""
            error = stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") if stderr else ""
            if stdout and len(stdout) > MAX_OUTPUT_BYTES: output += "\n[stdout truncated]"
            if stderr and len(stderr) > MAX_OUTPUT_BYTES: error += "\n[stderr truncated]"
            return {"success": process.returncode == 0, "output": output, "error": error, "code": process.returncode}
        except asyncio.TimeoutError:
            if process is not None:
                try:
                    if os.name != "nt": os.killpg(process.pid, signal.SIGKILL)
                    else: process.kill()
                except ProcessLookupError: pass
                await process.wait()
            return {"success": False, "output": "", "error": f"Command timed out after {timeout} seconds.", "code": -1}
        except Exception as exc:
            return {"success": False, "output": "", "error": f"Error executing command: {exc}", "code": -1}

    @staticmethod
    async def _run_docker(workspace_dir: Path, command: str, timeout: int) -> dict:
        workspace = str(workspace_dir.resolve())
        docker_cmd = [
            "docker", "run", "--rm", "--network", "none",
            "--cpus", str(settings.execution_cpu_limit),
            "--memory", settings.execution_memory_limit,
            "--pids-limit", str(settings.execution_pids_limit),
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
            "-v", f"{workspace}:/workspace:rw",
            "-w", "/workspace",
            settings.execution_docker_image,
            "/bin/sh", "-lc", command,
        ]
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *docker_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout + 10)
            output = stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") if stdout else ""
            error = stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") if stderr else ""
            if stdout and len(stdout) > MAX_OUTPUT_BYTES: output += "\n[stdout truncated]"
            if stderr and len(stderr) > MAX_OUTPUT_BYTES: error += "\n[stderr truncated]"
            return {"success": process.returncode == 0, "output": output, "error": error, "code": process.returncode}
        except asyncio.TimeoutError:
            if process is not None:
                try: process.kill()
                except ProcessLookupError: pass
                await process.wait()
            return {"success": False, "output": "", "error": f"Sandbox timed out after {timeout} seconds.", "code": -1}
        except FileNotFoundError:
            return {"success": False, "output": "", "error": "Docker is required for EXECUTION_MODE=docker but was not found. Set EXECUTION_MODE=process only for trusted local development.", "code": -1}
        except Exception as exc:
            return {"success": False, "output": "", "error": f"Sandbox execution error: {exc}", "code": -1}

    @staticmethod
    async def run(workspace_dir: Path, command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
        workspace_dir = workspace_dir.resolve()
        if not workspace_dir.exists() or not workspace_dir.is_dir():
            return {"success": False, "output": "", "error": "Workspace directory does not exist.", "code": -1}
        if not isinstance(command, str) or not command.strip():
            return {"success": False, "output": "", "error": "Command is empty.", "code": -1}
        if len(command) > MAX_COMMAND_LENGTH:
            return {"success": False, "output": "", "error": f"Command exceeds the {MAX_COMMAND_LENGTH} character limit.", "code": -1}
        try: timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        except (TypeError, ValueError): timeout = DEFAULT_TIMEOUT
        if settings.execution_mode.lower() == "process":
            return await CommandExecutor._run_process(workspace_dir, command, timeout)
        return await CommandExecutor._run_docker(workspace_dir, command, timeout)
