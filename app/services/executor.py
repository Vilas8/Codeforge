import os
import subprocess
from pathlib import Path
import asyncio

class CommandExecutor:
    """Safely executes commands within the workspace sandbox."""
    
    @staticmethod
    async def run(workspace_dir: Path, command: str, timeout: int = 30) -> dict:
        # Basic command sanitization (Do not allow changing directory above workspace)
        if ".." in command:
            return {"success": False, "output": "Path traversal detected in command."}
        
        try:
            # Run command asynchronously with timeout
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(workspace_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            
            success = process.returncode == 0
            output = stdout.decode() if stdout else ""
            error_output = stderr.decode() if stderr else ""
            
            return {
                "success": success,
                "output": output,
                "error": error_output,
                "code": process.returncode
            }
        except asyncio.TimeoutError:
            process.kill()
            return {"success": False, "output": f"Command timed out after {timeout} seconds."}
        except Exception as e:
            return {"success": False, "output": f"Error executing command: {str(e)}"}
