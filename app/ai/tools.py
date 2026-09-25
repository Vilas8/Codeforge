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
        try:
            target = WorkspaceManager.safe_path(self.user_id, self.project_id, path, allow_empty=True)
        except ValueError as exc:
            return "Error: " + str(exc)
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
        try:
            target = WorkspaceManager.safe_path(self.user_id, self.project_id, path)
        except ValueError as exc:
            return "Error: " + str(exc)
        if not target.exists() or not target.is_file():
            return "Error: File not found"
            
        with open(target, 'r', encoding='utf-8') as f:
            return f.read()

    def write_file(self, path: str, content: str) -> str:
        try:
            target = WorkspaceManager.safe_path(self.user_id, self.project_id, path)
        except ValueError as exc:
            return "Error: " + str(exc)
        with WorkspaceManager.workspace_lock(self.user_id, self.project_id):
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
        return f"File {path} written successfully."

    def search_files(self, query: str, limit: int = 12) -> str:
        if not isinstance(query, str) or not query.strip():
            return 'Error: Search query is empty.'
        try:
            from app.services.context import WorkspaceContextService
            results = WorkspaceContextService.search(self.user_id, self.project_id, query, max(1, min(int(limit), 30)))
            if not results:
                return 'No matching files found.'
            return '\n\n'.join(
                f"[{item.get('score', 0)}] {item.get('path')}\n{item.get('preview', '')[:1800]}"
                for item in results
            )
        except Exception as exc:
            return 'Error: workspace search failed: ' + str(exc)

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
                    "name": "search_files",
                    "description": "Search the project workspace for relevant files and return ranked previews. Use this before reading likely files when the task is unfamiliar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Filename, symbol, error message, or concept to search for"},
                            "limit": {"type": "integer", "description": "Maximum number of matching files, up to 30"}
                        },
                        "required": ["query"]
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
