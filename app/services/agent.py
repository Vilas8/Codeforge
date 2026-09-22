import json
from app.ai.client import get_ai_client, get_model, get_wire_api
from app.ai.prompts import AGENT_SYSTEM_PROMPT
from app.ai.tools import AgentTools

MODE_CONFIG = {
    "plan": {"label":"Plan","task":"planning","max_steps":12,"max_tool_calls":24,"max_file_changes":0,"allowed_tools":{"list_files","read_file"},"instruction":"Create a concrete implementation plan. Inspect the relevant workspace first. Do not modify files or run commands."},
    "explain": {"label":"Explain","task":"coding","max_steps":14,"max_tool_calls":28,"max_file_changes":0,"allowed_tools":{"list_files","read_file"},"instruction":"Explain the existing project, architecture and code clearly. Inspect relevant files first and do not modify files."},
    "build": {"label":"Build","task":"coding","max_steps":30,"max_tool_calls":60,"max_file_changes":50,"allowed_tools":{"list_files","read_file","write_file","run_command"},"instruction":"Implement the requested feature end-to-end. Inspect before modifying, then validate with relevant commands."},
    "debug": {"label":"Debug","task":"debug","max_steps":30,"max_tool_calls":60,"max_file_changes":50,"allowed_tools":{"list_files","read_file","write_file","run_command"},"instruction":"Reproduce or inspect the reported failure, identify the root cause, fix it, and rerun the relevant validation. Iterate until fixed or the budget is exhausted."},
    "review": {"label":"Review","task":"review","max_steps":18,"max_tool_calls":36,"max_file_changes":0,"allowed_tools":{"list_files","read_file","run_command"},"instruction":"Review correctness, security, maintainability and test coverage. Do not modify files."},
    "test": {"label":"Test","task":"coding","max_steps":24,"max_tool_calls":48,"max_file_changes":0,"allowed_tools":{"list_files","read_file","run_command"},"instruction":"Discover and run the most relevant tests/checks. Diagnose failures and report root causes. Do not modify files."},
    "refactor": {"label":"Refactor","task":"coding","max_steps":30,"max_tool_calls":60,"max_file_changes":50,"allowed_tools":{"list_files","read_file","write_file","run_command"},"instruction":"Improve structure, readability and maintainability without changing intended behavior. Read affected files first and validate afterward."},
    "security": {"label":"Security","task":"review","max_steps":20,"max_tool_calls":40,"max_file_changes":0,"allowed_tools":{"list_files","read_file","run_command"},"instruction":"Perform a security-focused review for secrets, injection, authentication, authorization, unsafe file access and command execution risks. Do not modify files."},
    "optimize": {"label":"Optimize","task":"coding","max_steps":30,"max_tool_calls":60,"max_file_changes":50,"allowed_tools":{"list_files","read_file","write_file","run_command"},"instruction":"Find measurable performance, reliability or resource-efficiency improvements. Inspect first, make targeted changes and validate."},
}
MODE_INSTRUCTIONS = {name: cfg["instruction"] for name, cfg in MODE_CONFIG.items()}


class CodeForgeAgent:
    def __init__(self, user_id, project_id, stream_callback=None, task="coding", mode="build", model=None):
        self.user_id = user_id
        self.project_id = project_id
        self.tools = AgentTools(user_id, project_id)
        self.stream_callback = stream_callback
        self.mode = mode if mode in MODE_CONFIG else "build"
        self.mode_config = MODE_CONFIG[self.mode]
        self.task = self.mode_config["task"]
        self.model = model or get_model(self.task)
        self.tool_calls = 0
        self.file_changes = 0
        self.ai_client = get_ai_client()
        self.wire_api = get_wire_api(self.model)
        self.response_id = None
        self.pending_response_outputs = []
        self.messages = [{
            "role": "system",
            "content": AGENT_SYSTEM_PROMPT + "\n\nCURRENT AGENT MODE: " + MODE_CONFIG[self.mode]["label"] + "\n\nMODE POLICY:\n" + MODE_INSTRUCTIONS[self.mode] + "\n\nHARD LIMITS: max steps=" + str(MODE_CONFIG[self.mode]["max_steps"]) + ", max tool calls=" + str(MODE_CONFIG[self.mode]["max_tool_calls"]) + ", max file changes=" + str(MODE_CONFIG[self.mode]["max_file_changes"]),
        }]

    async def emit(self, event):
        if self.stream_callback:
            await self.stream_callback(event)

    async def execute_tool(self, name, args):
        if name not in self.mode_config["allowed_tools"]:
            result = f"Tool '{name}' is not allowed in {self.mode} mode."
            await self.emit({"type": "tool_result", "tool": name, "success": False, "result": result})
            return result
        if self.tool_calls >= self.mode_config["max_tool_calls"]:
            result = "Agent tool-call budget exhausted."
            await self.emit({"type": "budget", "kind": "tool_calls", "limit": self.mode_config["max_tool_calls"]})
            return result
        if name == "write_file" and self.file_changes >= self.mode_config["max_file_changes"]:
            result = "Agent file-change budget exhausted."
            await self.emit({"type": "budget", "kind": "file_changes", "limit": self.mode_config["max_file_changes"]})
            return result
        self.tool_calls += 1
        if name == "run_command" and self.mode_config["max_file_changes"] == 0:
            command = str(args.get("command", "")).strip().lower()
            blocked = ("rm ", "rm -", "mv ", "cp ", "touch ", "mkdir ", "rmdir ", "del ", "copy ", "move ", "git reset", "git checkout", "git clean", "npm install", "pip install", "poetry install", " > ", " >> ", "python -c", "node -e", "curl ", "wget ")
            if any(token in command for token in blocked):
                result = "Command blocked by read-only agent mode."
                await self.emit({"type": "tool_result", "tool": name, "success": False, "result": result})
                return result
        await self.emit({"type": "tool_call", "tool": name, "args": args, "mode": self.mode})
        try:
            if name == "list_files":
                result = self.tools.list_files(args.get("path", "."))
            elif name == "read_file":
                result = self.tools.read_file(args.get("path"))
            elif name == "write_file":
                path = args.get("path")
                before = self.tools.read_file(path)
                result = self.tools.write_file(path, args.get("content"))
                self.file_changes += 1
                after = self.tools.read_file(path)
                await self.emit({
                    "type": "file_change",
                    "path": path,
                    "operation": "write",
                    "created": before.startswith("Error:"),
                    "before": "" if before.startswith("Error:") else before,
                    "after": "" if after.startswith("Error:") else after,
                })
            elif name == "run_command":
                result = await self.tools.run_command(args.get("command"))
            else:
                result = f"Unknown tool: {name}"

            result_text = str(result)
            success = not result_text.startswith("Error:")
            if name == "run_command":
                success = "Exit code: 0" in result_text

            await self.emit({
                "type": "tool_result",
                "tool": name,
                "success": success,
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

    async def run(self, user_prompt):
        self.messages.append({"role": "user", "content": user_prompt})
        await self.emit({"type": "mode", "mode": self.mode, "label": self.mode_config["label"], "limits": {k:self.mode_config[k] for k in ("max_steps","max_tool_calls","max_file_changes")}})
        if self.wire_api == "responses":
            return await self._run_responses()
        return await self._run_chat_completions()

    async def _run_chat_completions(self):
        for _step in range(self.mode_config["max_steps"]):
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
                        await self.emit({
                            "type": "tool_result",
                            "tool": tool_call["function"]["name"],
                            "success": False,
                            "result": result,
                        })
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

        raise RuntimeError(f"Agent stopped after {self.mode_config["max_steps"]} steps without completing.")

    async def _run_responses(self):
        system = self.messages[0]["content"]
        user_input = [{"role": "user", "content": self.messages[-1]["content"]}]

        for _step in range(MAX_AGENT_STEPS):
            kwargs = {
                "model": self.model,
                "instructions": system,
                "tools": self._responses_tools(),
                "stream": True,
            }

            if self.response_id is None:
                kwargs["input"] = user_input
            else:
                kwargs["previous_response_id"] = self.response_id
                kwargs["input"] = self.pending_response_outputs

            stream = await self.ai_client.responses.create(**kwargs)
            content_parts = []
            tool_calls = {}

            async for event in stream:
                event_type = getattr(event, "type", "")

                if event_type == "error":
                    raise RuntimeError(
                        getattr(event, "message", None) or "Responses API streaming error."
                    )

                if event_type in {"response.created", "response.in_progress", "response.completed"}:
                    response = getattr(event, "response", None)
                    response_id = getattr(response, "id", None)
                    if response_id:
                        self.response_id = response_id

                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or ""
                    if delta:
                        content_parts.append(delta)
                        await self.emit({"type": "message_delta", "content": delta})
                    continue

                if event_type == "response.output_item.added":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", None) == "function_call":
                        item_id = getattr(item, "id", None) or getattr(event, "item_id", None)
                        if item_id:
                            tool_calls[item_id] = {
                                "id": item_id,
                                "call_id": getattr(item, "call_id", None) or "",
                                "name": getattr(item, "name", None) or "",
                                "arguments": getattr(item, "arguments", None) or "",
                            }
                    continue

                if event_type == "response.function_call_arguments.delta":
                    item_id = getattr(event, "item_id", None)
                    if not item_id:
                        continue
                    call = tool_calls.setdefault(item_id, {
                        "id": item_id,
                        "call_id": "",
                        "name": "",
                        "arguments": "",
                    })
                    call["arguments"] += getattr(event, "delta", "") or ""
                    continue

                if event_type == "response.function_call_arguments.done":
                    item_id = getattr(event, "item_id", None)
                    if not item_id:
                        continue
                    call = tool_calls.setdefault(item_id, {
                        "id": item_id,
                        "call_id": "",
                        "name": "",
                        "arguments": "",
                    })
                    arguments = getattr(event, "arguments", None)
                    if arguments is not None:
                        call["arguments"] = arguments
                    if getattr(event, "name", None):
                        call["name"] = event.name
                    continue

                if event_type == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", None) == "function_call":
                        item_id = getattr(item, "id", None) or getattr(event, "item_id", None)
                        if item_id:
                            call = tool_calls.setdefault(item_id, {
                                "id": item_id,
                                "call_id": "",
                                "name": "",
                                "arguments": "",
                            })
                            call["call_id"] = getattr(item, "call_id", None) or call["call_id"]
                            call["name"] = getattr(item, "name", None) or call["name"]
                            call["arguments"] = getattr(item, "arguments", None) or call["arguments"]
                    continue

            content = "".join(content_parts)
            normalized_tool_calls = list(tool_calls.values())

            if not normalized_tool_calls:
                await self.emit({"type": "message", "content": content})
                return content

            self.pending_response_outputs = []
            for call in normalized_tool_calls:
                name = call["name"]
                call_id = call["call_id"]

                if not name or not call_id:
                    result = "Responses API returned an incomplete function call."
                    await self.emit({
                        "type": "tool_result",
                        "tool": name or "unknown",
                        "success": False,
                        "result": result,
                    })
                    if call_id:
                        self.pending_response_outputs.append({
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result,
                        })
                    continue

                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    result = f"Tool arguments were invalid JSON: {exc}"
                    await self.emit({
                        "type": "tool_result",
                        "tool": name,
                        "success": False,
                        "result": result,
                    })
                    self.pending_response_outputs.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result,
                    })
                    continue

                result = await self.execute_tool(name, args)
                self.pending_response_outputs.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result,
                })

        raise RuntimeError(f"Agent stopped after {MAX_AGENT_STEPS} tool steps without completing.")

    @staticmethod
    def _responses_tools():
        return [
            {
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            }
            for item in AgentTools.get_tool_schemas()
            for fn in [item["function"]]
        ]
