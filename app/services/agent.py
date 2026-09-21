import json
from app.ai.client import ai_client, get_model
from app.ai.prompts import AGENT_SYSTEM_PROMPT
from app.ai.tools import AgentTools

MODE_INSTRUCTIONS = {
    "build": "Focus on implementing the requested feature end-to-end. Make the necessary file changes and validate them.",
    "review": "Focus on reviewing the existing implementation for bugs, risks, maintainability issues, and concrete fixes. Do not change code unless the user asks for fixes.",
    "debug": "Focus on reproducing, diagnosing, and fixing the reported problem. Inspect relevant files before changing them and validate the fix.",
    "explain": "Focus on explaining the existing project and code clearly. Read the relevant files and avoid modifying them unless explicitly requested.",
}

class CodeForgeAgent:
    def __init__(self, project_id: str, stream_callback=None, task: str = "coding", mode: str = "build"):
        self.project_id = project_id
        self.tools = AgentTools(project_id)
        self.stream_callback = stream_callback
        self.task = task if task in {"planning", "coding", "review", "debug"} else "coding"
        self.mode = mode if mode in MODE_INSTRUCTIONS else "build"
        self.messages = [{
            "role": "system",
            "content": AGENT_SYSTEM_PROMPT + "\n\nCURRENT AGENT MODE:\n" + MODE_INSTRUCTIONS[self.mode]
        }]

    async def emit(self, event: dict):
        if self.stream_callback:
            await self.stream_callback(event)

    async def execute_tool(self, name: str, args: dict) -> str:
        await self.emit({"type": "tool_call", "tool": name, "args": args})
        try:
            if name == "list_files":
                result = self.tools.list_files(args.get("path", "."))
            elif name == "read_file":
                result = self.tools.read_file(args.get("path"))
            elif name == "write_file":
                path = args.get("path")
                before = self.tools.read_file(path)
                result = self.tools.write_file(path, args.get("content"))
                after = self.tools.read_file(path)
                await self.emit({
                    "type": "file_change",
                    "path": path,
                    "operation": "write",
                    "before": "" if before.startswith("Error:") else before,
                    "after": "" if after.startswith("Error:") else after,
                })
            elif name == "run_command":
                result = await self.tools.run_command(args.get("command"))
            else:
                result = f"Unknown tool: {name}"

            result_text = str(result)
            await self.emit({
                "type": "tool_result",
                "tool": name,
                "success": True,
                "result": result_text[-6000:],
            })
            return result_text
        except Exception as exc:
            message = str(exc)
            await self.emit({
                "type": "tool_result",
                "tool": name,
                "success": False,
                "result": message,
            })
            return "Tool failed: " + message

    async def run(self, user_prompt: str) -> str:
        self.messages.append({"role": "user", "content": user_prompt})
        while True:
            response = await ai_client.chat.completions.create(
                model=get_model(self.task),
                messages=self.messages,
                tools=AgentTools.get_tool_schemas(),
                tool_choice="auto",
            )
            message = response.choices[0].message
            self.messages.append(message)

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    args = json.loads(tool_call.function.arguments)
                    result = await self.execute_tool(tool_call.function.name, args)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": result,
                    })
            else:
                if self.stream_callback:
                    await self.stream_callback({"type": "message", "content": message.content})
                return message.content
