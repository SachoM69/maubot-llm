from maubot import Plugin
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command, event
from mautrix.types import EventType, MessageEvent
from typing import Type
from maubot_llm.backends import Backend, BasicOpenAIBackend
from maubot_llm import db
from mautrix.util.async_db import UpgradeTable
from mautrix.client import Client as MatrixClient, SyncStream
import json
import datetime
from html.parser import HTMLParser

class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("allowlist")
        helper.copy("default_backend")
        helper.copy("backends")

class LlmCancellationToken():
    def __init__(self):
        self.cancellation_requested = False
        self.dependent_query = None

    def set_query(self, query):
        self.dependent_query = query

    def cancel(self):
        if (self.dependent_query):
            self.dependent_query.cancel()
        self.cancellation_requested = True

    def is_cancellation_requested(self):
        return self.cancellation_requested


class LlmBot(Plugin):
    async def start(self) -> None:
        self.config.load_and_update()
        self.in_flight = {}
        self.is_tool_debug = False
    
    def is_allowed(self, sender: str) -> bool:
        if self.config["allowlist"] == False:
            return True
        return sender in self.config["allowlist"]

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config
    
    async def get_room(self, room_id: str) -> db.Room:
        room = await db.fetch_room(self.database, room_id)
        if room is None:
            room = db.Room()
            room.room_id = room_id
            await db.upsert_room(self.database, room)
        return room
    
    def get_backend(self, room: db.Room) -> Backend:
        key = room.backend
        if key is None:
            key = self.config["default_backend"]
        cfg = self.config["backends"][key]
        cfg["key"] = key
        if cfg["type"] == "basic_openai":
            return BasicOpenAIBackend(cfg)
        raise ValueError(f"unknown backend type {cfg['type']}")
    
    @command.new(name="llm-out")
    @command.argument("prompt", pass_raw=True)
    def llm_out_command(self, evt: MessageEvent, prompt: str) -> None:
        pass

    @command.new(name="llm", require_subcommand=True)
    async def llm_command(self, evt: MessageEvent) -> None:
        pass

    @llm_command.subcommand(help="Display configuration used for current room.")
    async def info(self, evt: MessageEvent) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        room = await self.get_room(evt.room_id)
        context = await db.fetch_context(self.database, room.room_id)
        backend = self.get_backend(room)
        all_backends = ", ".join(self.config["backends"].keys())

        all_models = "unknown"
        try:
            all_models = ", ".join(await backend.fetch_models(self.http))
        except:
            pass

        items = []
        items.append("!llm-out")
        items.append(f"- Backend: {backend.cfg['key']} (available: {all_backends})")
        if room.model:
            items.append(f"- Model: {room.model}")
        elif backend.default_model:
            items.append(f"- Model (backend default): {backend.default_model}")
        else:
            items.append("- Model not specified")
        items[-1] += f" (available: {all_models})"
        if room.system_prompt:
            items.append(f"- System Prompt: {room.system_prompt}")
        elif backend.default_system_prompt:
            items.append(f"- System Prompt (backend default): {backend.default_system_prompt}")
        else:
            items.append("- System Prompt not specified")
        items.append(f"- Context Message Count: {len(context)}")
        request = self.in_flight.get(evt.room_id, None)
        if request:
            items.append("- A request is in-flight for this room")
        else:
            items.append("- No requests in-flight for this room")
        msg = "\n".join(items)
        await evt.reply(msg)
    
    @llm_command.subcommand(help="Switch to a different backend for this room.")
    @command.argument("key")
    async def backend(self, evt: MessageEvent, key: str) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        if key not in self.config["backends"].keys():
            all_backends = ", ".join(self.config["backends"].keys())
            msg = f"!llm-out Invalid backend. Available backends: {all_backends}"
            await evt.reply(msg)
            return
        room = await self.get_room(evt.room_id)
        room.backend = key
        await db.upsert_room(self.database, room)
        await evt.react("✅")
    
    @llm_command.subcommand(help="Switch to a different model for this room. Use '-' to switch to the backend's default model.")
    @command.argument("model")
    async def model(self, evt: MessageEvent, model: str) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        # TODO validate model when the backend supports it
        room = await self.get_room(evt.room_id)
        if model == "-":
            room.model = None
        else:
            room.model = model
        await db.upsert_room(self.database, room)
        await evt.react("✅")
    
    @llm_command.subcommand(help="Switch to a different system prompt for this room. Use '-' to switch to the backend's default system prompt.")
    @command.argument("prompt", pass_raw=True)
    async def system(self, evt: MessageEvent, prompt: str) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        # TODO validate model when the backend supports it
        room = await self.get_room(evt.room_id)

        mentions = evt.content.get("m.mentions")
        if mentions:
            ids = mentions.get("user_ids")
            if self.client.mxid not in ids:
                return

        if prompt == "-":
            room.system_prompt = None
        else:
            room.system_prompt = prompt
        await db.upsert_room(self.database, room)
        await evt.react("✅")

    @llm_command.subcommand(help="Forget all context and treat subsequent messages as part of a new chat with the LLM. Also cancels the current in-flight request.")
    async def clear(self, evt: MessageEvent) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        await db.clear_context(self.database, evt.room_id)

        request = self.in_flight.get(evt.room_id, None)
        if request:
            request.cancel()
            self.in_flight[evt.room_id] = None

        await evt.react("✅")
        
    @llm_command.subcommand(help="Enable/disable output of tool results directly into chat.")
    @command.argument("enable")
    async def tool_debug(self, evt: MessageEvent, enable : bool) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        
        self.is_tool_debug = enable
        await evt.react("✅")

    @llm_command.subcommand(help="Interrupt the current in-flight request.")
    async def cancel(self, evt: MessageEvent) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        request = self.in_flight.get(evt.room_id, None)
        if request:
            request.cancel()
            self.in_flight[evt.room_id] = None
            await evt.react("✅")
            await self.client.set_typing(evt.room_id, 0)
        else:
            await evt.react("idle")

    @event.on(EventType.ROOM_MESSAGE)
    async def handle_msg(self, evt: MessageEvent) -> None:
        if evt.content.body.startswith("!"):
            return
        
        if evt.sender == self.client.mxid:
            await db.append_context(self.database, evt.room_id, "assistant", evt.content.body)
            return
            
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        
        user_name = ""
        mems = await self.client.get_joined_members(evt.room_id)
        member = mems.get(evt.sender, None)
        if member:
            user_name += "\n<username>" + member.displayname + "</username>"

        mentions = evt.content.get("m.mentions")
        if mentions:
            ids = mentions.get("user_ids")
            if self.client.mxid not in ids:
                await db.append_context(self.database, evt.room_id, "user", evt.content.body + user_name)
                return

        # if a request is in flight, cancel it
        old_token = self.in_flight.get(evt.room_id, None)
        if old_token:
            old_token.cancel()
        my_token = LlmCancellationToken()
        self.in_flight[evt.room_id] = my_token

        room = await self.get_room(evt.room_id)
        await db.append_context(self.database, room.room_id, "user", evt.content.body + user_name)
        await evt.mark_read()
        if (my_token.is_cancellation_requested()): return
        # TODO: refresh the typing indicator if generation takes longer
        # (or, alternatively, set a timeout for generation)
        try:
            backend = self.get_backend(room)
            model = room.model or backend.default_model
            system = room.system_prompt or backend.default_system_prompt
            context = await db.fetch_context(self.database, room.room_id)

            await self.complete_with_tools(evt, backend, model, system, context, my_token)
        except Exception as e:
            self.log.error(f'[maubot_llm] [handle_msg] {e}')
            raise
        finally:
            if (not my_token.is_cancellation_requested()):
                await self.client.set_typing(evt.room_id, 0)

    async def complete_with_tools(self, evt: MessageEvent, backend, model, system, context, cancellation_token) -> None:
        message_parts = []
        while True:
            await self.client.set_typing(evt.room_id, 30000)
            if (cancellation_token.is_cancellation_requested()): return
            request = backend.create_chat_completion(self.http, context=context, system=system, model=model, tools=self.known_tools)
            cancellation_token.set_query(request)
            response = await request.resolve_request()
            if (cancellation_token.is_cancellation_requested()): return
            if (response.get("choices", None) == None):
                error = response.get("message", None)
                code = response.get("code", None)
                type = response.get("type", None)
                self.log.error(f'[maubot_llm] {code} {type}. {error}')
                return
            
            prime_choice = response["choices"][0]
            if prime_choice["message"]["content"] in ['💤', ''] and prime_choice["finish_reason"] != "tool_calls":
                break
            message_parts.append(prime_choice["message"]["content"])
            if prime_choice["finish_reason"] != "tool_calls":
                break

            context.append(prime_choice["message"])
            tool_calls = prime_choice["message"]["tool_calls"]
            for call in tool_calls:
                if call["type"] != "function":
                    self.log.info(f'[maubot_llm] [complete_with_tools] Wrong tool type! Got {call["type"]}, expected function')
                    continue
                try:
                    self.log.info(f'calling tool')
                    params = call["function"]
                    self.log.info(params)
                    tool_args = json.loads(params["arguments"])
                    tool_result = await self.call_tool(evt, params["name"], call["id"], tool_args)
                    self.log.info(tool_result)

                    if tool_result:
                        context.append(tool_result)

                        if self.is_tool_debug:
                            await evt.respond("!llm-tool-out: " + str(tool_result))
                except Exception as exc:
                    self.log.error(f'[maubot_llm] [tool_call] {exc}')


        response_text = "\n".join(message_parts)
        if (response_text in ['💤', '']):
            await evt.react("💤")
        else:
            await evt.respond(response_text)

    async def call_tool(self, evt: MessageEvent, tool_name, call_id, args):
        tool_result = None
        if tool_name == "react":
            await evt.react(args["key"])
            tool_result = {"role":"tool", "tool_call_id": call_id, "content": "Reaction was sent successfully"}
        elif tool_name == "get_current_datetime":
            now = datetime.datetime.now()
            tool_result = {"role":"tool", "tool_call_id": call_id, "content": f'{{\"current_timestamp\": {now.timestamp()}, \"current_iso\": \"{now.astimezone(datetime.timezone.utc).isoformat()}\", \"user_local_iso\": \"{now.astimezone().isoformat()}\", \"user_timezone\": \"{now.astimezone().tzname()}\"}}'}
        elif tool_name == "fetch_url":
            url = args["url"]
            html_custom_headers = {"User-Agent": "WhatsApp/2"}
            resp = await self.http.get(url, timeout=30, headers=html_custom_headers)
            if resp.status != 200:
                tool_result = {"role":"tool", "tool_call_id": call_id, "content": f'{{\"error\": \"{resp.status} {resp.reason}\"}}'}
            else:
                cont = await resp.text()
                parser = ExtractMetaTags()
                parser.feed(cont)
                tool_result = {"role":"tool", "tool_call_id": call_id, "content": f'{{\"status\": \"success\", \"text\": \"{parser.result}\"}}'}

        return tool_result
    
    known_tools = [
        {
            "type": "function",
            "function": {
                "name": "react",
                "description": "React to the message with the given key. The key can be arbitrary unicode text, but usually reactions are emojis.",
                "parameters": {
                    "properties": {
                        "key": {
                            "description": "Reaction key",
                            "type": "string"
                        }
                    },
                    "required": [
                        "key"
                    ],
                    "type": "object"
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Load the url contents",
                "parameters": {
                    "properties": {
                        "url": {
                            "description": "The address to fetch",
                            "type": "string"
                        }
                    },
                    "required": [
                        "url"
                    ],
                    "type": "object"
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_datetime",
                "description": "Get the current date, time and timezone.",
                "parameters": {
                    "properties": {},
                    "type": "object"
                }
            }
        },
    ]    
    
    @classmethod
    def get_db_upgrade_table(cls) -> UpgradeTable | None:
        return db.upgrade_table

class ExtractMetaTags(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.result = ""
        self.current_tag = ""

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        # if tag not in ["path", "g", "symbol", "div", "span"]:
        #     self.result += f'{tag}: {attrs}\n'
            
    def handle_data(self, data):
        if (self.current_tag == "script"): return
        data = data.strip()
        if len(data):
            self.result += f'{data}\n'