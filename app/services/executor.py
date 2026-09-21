import asyncio
import os
import signal
from pathlib import Path

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
MAX_COMMAND_LENGTH = 12000
MAX_OUTPUT_BYTES = 100_000

# Keep only non-sensitive runtime variables needed by common build tools.
SAFE_ENV_KEYS = {
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SHELL",
    "TERM",
    "CI",
    "NODE_ENV",
    "PYTHONUNBUFFERED",
}

class CommandExecutor:
    """Execute project commands with bounded time, output, and environment."""

    @staticmethod
    async def run(workspace_dir: Path, command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
        workspace_dir = workspace_dir.resolve()

        if not workspace_dir.exists() or not workspace_dir.is_dir():
            return {
                "success": False,
                "output": "",
                "error": "Workspace directory does not exist.",
                "code": -1,
            }

        if not isinstance(command, str) or not command.strip():
            return {
                "success": False,
                "output": "",
                "error": "Command is empty.",
                "code": -1,
            }

        if len(command) > MAX_COMMAND_LENGTH:
            return {
                "success": False,
                "output": "",
                "error": f"Command exceeds the {MAX_COMMAND_LENGTH} character limit.",
                "code": -1,
            }

        try:
            timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT

        # Never inherit the server's environment wholesale: it may contain
        # Supabase service-role keys or other application secrets.
        env = {
            key: value
            for key, value in os.environ.items()
            if key in SAFE_ENV_KEYS
        }
        env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
        env["CODEFORGE_WORKSPACE"] = str(workspace_dir)

        process = None
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(workspace_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name != "nt"),
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

            output = stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") if stdout else ""
            error_output = stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") if stderr else ""
            if stdout and len(stdout) > MAX_OUTPUT_BYTES:
                output += "\n[stdout truncated]"
            if stderr and len(stderr) > MAX_OUTPUT_BYTES:
                error_output += "\n[stderr truncated]"

            code = process.returncode
            return {
                "success": code == 0,
                "output": output,
                "error": error_output,
                "code": code,
            }

        except asyncio.TimeoutError:
            if process is not None:
                try:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

            return {
                "success": False,
                "output": "",
                "error": f"Command timed out after {timeout} seconds.",
                "code": -1,
            }

        except Exception as exc:
            if process is not None and process.returncode is None:
                try:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    await process.wait()
                except (ProcessLookupError, OSError):
                    pass

            return {
                "success": False,
                "output": "",
                "error": f"Error executing command: {exc}",
                "code": -1,
            }
