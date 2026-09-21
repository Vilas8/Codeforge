import json
import asyncio
from app.ai.client import ai_client, get_model
from app.ai.prompts import AGENT_SYSTEM_PROMPT
from app.ai.tools import AgentTools

class CodeForgeAgent:
    def __init__(self, project_id: str, stream_callback=None):
        self.project_id = project_id
        self.tools = AgentTools(project_id)
        self.stream_callback = stream_callback
        self.messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT}
        ]

    async def execute_tool(self, name: str, args: dict) -> str:
        if self.stream_callback:
            await self.stream_callback({"type": "tool_call", "tool": name, "args": args})
            
        if name == "list_files":
            return self.tools.list_files(args.get("path", "."))
        elif name == "read_file":
            return self.tools.read_file(args.get("path"))
        elif name == "write_file":
            if self.stream_callback:
                await self.stream_callback({"type": "file_change", "path": args.get("path"), "operation": "write"})
            return self.tools.write_file(args.get("path"), args.get("content"))
        elif name == "run_command":
            return await self.tools.run_command(args.get("command"))
        else:
            return f"Unknown tool: {name}"

    async def run(self, user_prompt: str) -> str:
        self.messages.append({"role": "user", "content": user_prompt})
        
        while True:
            response = await ai_client.chat.completions.create(
                model=get_model("coding"),
                messages=self.messages,
                tools=AgentTools.get_tool_schemas(),
                tool_choice="auto"
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
                        "content": result
                    })
                # Loop continues back to model with tool results
            else:
                # No more tools, generation is complete
                if self.stream_callback:
                    await self.stream_callback({"type": "message", "content": message.content})
                return message.content
