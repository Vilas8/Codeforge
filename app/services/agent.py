import json
from app.ai.client import get_ai_client, get_model, get_provider_for_model
from app.ai.prompts import AGENT_SYSTEM_PROMPT
from app.ai.tools import AgentTools

MODE_INSTRUCTIONS = {
    "build": "Focus on implementing the requested feature end-to-end. Make the necessary file changes and validate them.",
    "review": "Focus on reviewing the existing implementation for bugs, risks, maintainability issues, and concrete fixes. Do not change code unless the user asks for fixes.",
    "debug": "Focus on reproducing, diagnosing, and fixing the reported problem. Inspect relevant files before changing them and validate the fix.",
    "explain": "Focus on explaining the existing project and code clearly. Read the relevant files and avoid modifying them unless explicitly requested.",
}

MAX_AGENT_STEPS = 30

class CodeForgeAgent:
    def __init__(self, user_id, project_id, stream_callback=None, task="coding", mode="build", model=None):
        self.user_id = user_id
        self.project_id = project_id
        self.tools = AgentTools(user_id, project_id)
        self.stream_callback = stream_callback
        self.task = task if task in {"planning", "coding", "review", "debug"} else "coding"
        self.mode = mode if mode in MODE_INSTRUCTIONS else "build"
        self.model = model or get_model(self.task)
        self.provider = get_provider_for_model(self.model)
        self.ai_client = get_ai_client(self.provider)
        self.response_id = None
        self.pending_response_outputs = []
        self.messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT + "\n\nCURRENT AGENT MODE:\n" + MODE_INSTRUCTIONS[self.mode]}]

    async def emit(self, event):
        if self.stream_callback:
            await self.stream_callback(event)

    async def execute_tool(self, name, args):
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
                await self.emit({"type": "file_change", "path": path, "operation": "write",
                                 "created": before.startswith("Error:"),
                                 "before": "" if before.startswith("Error:") else before,
                                 "after": "" if after.startswith("Error:") else after})
            elif name == "run_command":
                result = await self.tools.run_command(args.get("command"))
            else:
                result = f"Unknown tool: {name}"
            result_text = str(result)
            success = not result_text.startswith("Error:")
            if name == "run_command":
                success = "Exit code: 0" in result_text
            await self.emit({"type": "tool_result", "tool": name, "success": success, "result": result_text[-6000:]})
            return result_text
        except Exception as exc:
            message = str(exc)
            await self.emit({"type": "tool_result", "tool": name, "success": False, "result": message})
            return "Tool failed: " + message

    async def run(self, user_prompt):
        self.messages.append({"role": "user", "content": user_prompt})
        if self.provider == "codex":
            return await self._run_responses()
        return await self._run_chat_completions()

    async def _run_chat_completions(self):
        for _step in range(MAX_AGENT_STEPS):
            stream = await self.ai_client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=AgentTools.get_tool_schemas(),
                tool_choice="auto",
                stream=True,
            )

            content_parts = []
            tool_calls = {}

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    content_parts.append(delta.content)
                    await self.emit({"type": "message_delta", "content": delta.content})

                for tool_delta in (delta.tool_calls or []):
                    index = tool_delta.index
                    call = tool_calls.setdefault(index, {
                        "id": "",
                        "type": "function",
                        "name": "",
                        "arguments": "",
                    })
                    if tool_delta.id:
                        call["id"] = tool_delta.id
                    if tool_delta.type:
                        call["type"] = tool_delta.type
                    if tool_delta.function:
                        if tool_delta.function.name:
                            call["name"] += tool_delta.function.name
                        if tool_delta.function.arguments:
                            call["arguments"] += tool_delta.function.arguments

            content = "".join(content_parts)
            normalized_tool_calls = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": call["arguments"],
                    },
                }
                for _, call in sorted(tool_calls.items())
            ]

            assistant_message = {"role": "assistant", "content": content or None}
            if normalized_tool_calls:
                assistant_message["tool_calls"] = normalized_tool_calls
            self.messages.append(assistant_message)

            if normalized_tool_calls:
                for tool_call in normalized_tool_calls:
                    try:
                        args = json.loads(tool_call["function"]["arguments"] or "{}")
                    except json.JSONDecodeError as exc:
                        result = f"Tool arguments were invalid JSON: {exc}"
                        await self.emit({"type": "tool_result", "tool": tool_call["function"]["name"], "success": False, "result": result})
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": tool_call["function"]["name"],
                            "content": result,
                        })
                        continue
                    result = await self.execute_tool(tool_call["function"]["name"], args)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "content": result,
                    })
                continue

            await self.emit({"type": "message", "content": content})
            return content
        raise RuntimeError(f"Agent stopped after {MAX_AGENT_STEPS} tool steps without completing.")

    async def _run_responses(self):
        system = self.messages[0]["content"]
        user_input = [{"role": "user", "content": self.messages[-1]["content"]}]
        for _step in range(MAX_AGENT_STEPS):
            kwargs = {"model": self.model, "instructions": system, "tools": self._responses_tools()}
            if self.response_id is None:
                kwargs["input"] = user_input
            else:
                kwargs["previous_response_id"] = self.response_id
                kwargs["input"] = self.pending_response_outputs
            response = await self.ai_client.responses.create(**kwargs)
            self.response_id = response.id
            tool_calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
            if not tool_calls:
                content = response.output_text or ""
                await self.emit({"type": "message", "content": content})
                return content
            self.pending_response_outputs = []
            for item in tool_calls:
                try:
                    args = json.loads(item.arguments or "{}")
                except json.JSONDecodeError as exc:
                    result = f"Tool arguments were invalid JSON: {exc}"
                    await self.emit({"type": "tool_result", "tool": item.name, "success": False, "result": result})
                    self.pending_response_outputs.append({"type": "function_call_output", "call_id": item.call_id, "output": result})
                    continue
                result = await self.execute_tool(item.name, args)
                self.pending_response_outputs.append({"type": "function_call_output", "call_id": item.call_id, "output": result})
        raise RuntimeError(f"Agent stopped after {MAX_AGENT_STEPS} tool steps without completing.")

    @staticmethod
    def _responses_tools():
        return [
            {"type": "function", "name": fn["name"], "description": fn.get("description", ""),
             "parameters": fn.get("parameters", {})}
            for item in AgentTools.get_tool_schemas()
            for fn in [item["function"]]
        ]
