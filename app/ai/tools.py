import os
from pathlib import Path
from app.projects.workspace import WorkspaceManager
from app.services.executor import CommandExecutor

class AgentTools:
    """Tools accessible to the AI coding agent within a project workspace."""
    
    def __init__(self, user_id: str, project_id: str):
        self.user_id = user_id
        self.project_id = project_id
        self.workspace_dir = WorkspaceManager.get_workspace_path(user_id, project_id)
    
    def list_files(self, path: str = ".") -> str:
        target = (self.workspace_dir / path).resolve()
        try:
            target.relative_to(self.workspace_dir.resolve())
        except ValueError:
            return "Error: Access denied (outside workspace)"
        if not target.exists():
            return "Error: Directory not found"
            
        result = []
        for root, dirs, files in os.walk(target):
            # Ignore hidden folders like .git
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            level = str(Path(root).relative_to(self.workspace_dir)).count(os.sep)
            indent = ' ' * 4 * level
            result.append(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 4 * (level + 1)
            for f in files:
                result.append(f"{subindent}{f}")
        return "\n".join(result)

    def read_file(self, path: str) -> str:
        target = (self.workspace_dir / path).resolve()
        try:
            target.relative_to(self.workspace_dir.resolve())
        except ValueError:
            return "Error: Access denied (outside workspace)"
        if not target.exists() or not target.is_file():
            return "Error: File not found"
            
        with open(target, 'r', encoding='utf-8') as f:
            return f.read()

    def write_file(self, path: str, content: str) -> str:
        target = (self.workspace_dir / path).resolve()
        try:
            target.relative_to(self.workspace_dir.resolve())
        except ValueError:
            return "Error: Access denied (outside workspace)"
            
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"File {path} written successfully."

    async def run_command(self, command: str) -> str:
        res = await CommandExecutor.run(self.workspace_dir, command)
        output = f"Exit code: {res['code']}\nSTDOUT:\n{res['output']}\nSTDERR:\n{res['error']}"
        return output

    # The schemas provided to the OpenAI API
    @staticmethod
    def get_tool_schemas():
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List all files in the current workspace or a specific directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path to list"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the contents of a specific file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write new content to a file, completely replacing existing content. Creates directories if needed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path"},
                            "content": {"type": "string", "description": "File content"}
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Run a shell command in the project workspace (e.g. npm test, python script.py).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The shell command to execute"}
                        },
                        "required": ["command"]
                    }
                }
            }
        ]
