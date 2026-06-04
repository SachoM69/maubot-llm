from maubot import MessageEvent
from aiohttp import ClientSession
from .tool_base import LLMTool
from .tools import React, GetDateTime, FetchUrl
from logging import Logger
from .cancellation_token import LlmCancellationToken

def get_default_tool_holder(logger: Logger):
    return LLMToolHolder([React, GetDateTime, FetchUrl], logger)

class LLMToolHolder:
    def __init__(self, tools_classes, logger):
        self.tools = {}
        self.log = logger
        for tool_class in tools_classes:
            tool = tool_class()
            self.tools[tool.GetName()] = tool
    
    tools: dict[str, LLMTool]
    log: Logger

    def get_descriptions(self, allowed_tools: list[str] | bool) -> list[dict]:
        result = []
        if isinstance(allowed_tools, bool):
            allowed_tools = self.tools.keys()
        for tool_name in allowed_tools:
            tool = self.tools.get(tool_name, None)
            if tool == None:
                self.log.info("Invalid tool name in enabled_tools: " + tool_name)
                continue
            result.append({
                "type": "function",
                "function": tool.GetDescriptionDict()
            })
        return result
    
    async def call_tool(self, tool_name, call_id, evt: MessageEvent, http: ClientSession, args, token: LlmCancellationToken):
        result = None
        try:
            result = await self.tools[tool_name].Execute(evt, http, args, token)
        except Exception as e:
            result = {"error": str(e)}
        if result == None:
            return None

        return {"role":"tool", "tool_call_id": call_id, "content": str(result)}