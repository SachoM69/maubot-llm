from .tool_base import LLMTool
from .cancellation_token import LlmCancellationToken

def get_default_tool_holder(allowed_tools: list[str] | bool):
    from .tools import React, GetDateTime, FetchUrl
    default_list = [React(), GetDateTime(), FetchUrl()]
    if isinstance(allowed_tools, bool):
        result_list = default_list
    else:
        result_list = [tool for tool in default_list if tool.GetName() in allowed_tools]

    holder = LLMToolHolder()
    holder.add_tools(result_list)
    return holder

class LLMToolHolder:
    def __init__(self):
        self.tools = {}
    
    tools: dict[str, LLMTool]

    def add_tools(self, tools : list[LLMTool]):
        for tool in tools:
            self.tools[tool.GetName()] = tool

    def get_descriptions(self) -> list[dict]:
        return [{
                "type": "function",
                "function": tool.GetDescriptionDict()
            } for tool in self.tools.values()]
    
    async def call_tool(self, tool_name, call_id, message_builder, args, token: LlmCancellationToken):
        result = None
        try:
            result = await self.tools[tool_name].Execute(message_builder, args, token)
        except Exception as e:
            result = {"error": str(e)}
        if result == None:
            return None

        return {"role":"tool", "tool_call_id": call_id, "content": str(result)}