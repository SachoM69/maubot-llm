from typing import Optional
from maubot import MessageEvent
from logging import Logger
import json
from aiohttp import ClientSession
from .cancellation_token import LlmCancellationToken
from .tool_holder import LLMToolHolder
from .backend_base import Backend

class MessageBuilder:
    def __init__(self, evt: MessageEvent, http: ClientSession, logger: Logger,
                backend : Backend, model: Optional[str], system : Optional[str], context : list[dict], tool_holder : LLMToolHolder):
        self.trigger_event = evt
        self.http = http
        self.logger = logger
        self.backend = backend
        self.model = model
        self.system = system
        self.context = context
        self.tool_holder = tool_holder

    trigger_event: MessageEvent
    http: ClientSession
    logger: Logger
    backend : Backend
    model: Optional[str]
    system : Optional[str]
    context : list[dict]
    tool_holder: LLMToolHolder
    cancellation_token : LlmCancellationToken
    
    async def build_with_tools(self, tool_debug_messages: bool, token : LlmCancellationToken) -> None:
        message_parts = []
        while True:
            response = await self.backend.create_chat_completion_raw(self.http, context=self.context, system=self.system, model=self.model, tools=self.tool_holder.get_descriptions())

            if (response.get("choices") == None):
                error = response.get("error")
                err_response = ""
                if not error:
                    err_response = str(response)
                else:
                    message = error.get("message", None)
                    code = error.get("code", None)
                    type = error.get("type", None)
                    err_response = f'{code} {type}. {message}'
                self.logger.error(f'[maubot_llm] {err_response}')
                await self.trigger_event.respond(f'!llm-err: {err_response}')
                return
            
            prime_choice = response["choices"][0]
            message_parts.append(prime_choice["message"]["content"])
            if prime_choice["finish_reason"] != "tool_calls":
                break

            self.context.append(prime_choice["message"])
            tool_calls = prime_choice["message"]["tool_calls"]
            for call in tool_calls:
                if call["type"] != "function":
                    self.logger.info(f'[maubot_llm] [complete_with_tools] Wrong tool type! Got {call["type"]}, expected function')
                    continue

                self.logger.info(f'calling tool')
                params = call["function"]
                if tool_debug_messages:
                    await self.trigger_event.respond("!llm-tool-in: `" + str(params) + "`")
                self.logger.info(params)
                tool_args = json.loads(params["arguments"])
                tool_result = await self.tool_holder.call_tool(params["name"], call["id"], self, tool_args, token)
                self.logger.info(tool_result)

                if tool_result:
                    self.context.append(tool_result)

                    if tool_debug_messages:
                        content = str(tool_result["content"])
                        if len(content) > 100:
                            content = content[:100] + "..."
                        await self.trigger_event.respond("!llm-tool-out: `" + content + "`")


        response_text = "\n".join(message_parts)
        if (response_text in ['💤', '']):
            await self.trigger_event.react("💤")
        else:
            await self.trigger_event.respond(response_text)