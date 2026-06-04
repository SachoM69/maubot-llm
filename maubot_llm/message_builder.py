from typing import Optional
from maubot import MessageEvent
from maubot.matrix import MaubotMatrixClient
from logging import Logger
import json
from aiohttp import ClientSession
from .cancellation_token import LlmCancellationToken
from .tool_holder import LLMToolHolder
from .backend_base import Backend

class MessageBuilder:
    def __init__(self, tool_holder : LLMToolHolder):
        self.tool_holder = tool_holder

    cfg: dict
    tool_holder: LLMToolHolder
    
    async def build_with_tools(self, evt: MessageEvent, http: ClientSession, client: MaubotMatrixClient, logger: Logger,
                               backend : Backend, model: Optional[str], system : Optional[str], context : list[dict],
                               allowed_tools: list[str] | bool, tool_debug_messages: bool,
                               cancellation_token : LlmCancellationToken) -> None:
        message_parts = []
        while True:
            await client.set_typing(evt.room_id, 30000)
            if (cancellation_token.is_cancellation_requested()): return
            request = backend.create_chat_completion(http, context=context, system=system, model=model, tools=self.tool_holder.get_descriptions(allowed_tools))
            cancellation_token.set_query(request)
            response = await request.resolve_request()
            if (cancellation_token.is_cancellation_requested()): return
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
                logger.error(f'[maubot_llm] {err_response}')
                await evt.respond(f'!llm-err: {err_response}')
                return
            
            prime_choice = response["choices"][0]
            message_parts.append(prime_choice["message"]["content"])
            if prime_choice["finish_reason"] != "tool_calls":
                break

            context.append(prime_choice["message"])
            tool_calls = prime_choice["message"]["tool_calls"]
            for call in tool_calls:
                if call["type"] != "function":
                    logger.info(f'[maubot_llm] [complete_with_tools] Wrong tool type! Got {call["type"]}, expected function')
                    continue

                logger.info(f'calling tool')
                params = call["function"]
                if tool_debug_messages:
                    await evt.respond("!llm-tool-in: `" + str(params) + "`")
                logger.info(params)
                tool_args = json.loads(params["arguments"])
                tool_result = await self.tool_holder.call_tool(params["name"], call["id"], evt, http, tool_args)
                logger.info(tool_result)

                if tool_result:
                    context.append(tool_result)

                    if tool_debug_messages:
                        content = str(tool_result["content"])
                        if len(content) > 100:
                            content = content[:100] + "..."
                        await evt.respond("!llm-tool-out: `" + content + "`")


        response_text = "\n".join(message_parts)
        if (response_text in ['💤', '']):
            await evt.react("💤")
        else:
            await evt.respond(response_text)