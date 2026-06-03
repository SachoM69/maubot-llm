from typing import Optional
from maubot import Plugin
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command, event
from mautrix.types import EventType
from mautrix.types.primitive import RoomID
from typing import Type
from maubot_llm import db
from mautrix.util.async_db import UpgradeTable
from mautrix.client import Client as MatrixClient, SyncStream
from .tool_holder import get_default_tool_holder, LLMToolHolder
from .backends import Backend, BasicOpenAIBackend
from .cancellation_token import LlmCancellationToken
from .message_builder import MessageBuilder

class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("allowlist")
        helper.copy("default_backend")
        helper.copy("backends")
        helper.copy_dict("tools")

class LlmBot(Plugin):
    async def start(self) -> None:
        self.config.load_and_update()
        self.in_flight = {}
        self.tool_holder = get_default_tool_holder(self.log)
        self.message_builder = MessageBuilder(self.tool_holder)

    in_flight: dict[RoomID, Optional[LlmCancellationToken]]
    tool_holder: LLMToolHolder
    
    def is_allowed(self, sender: str) -> bool:
        if self.config["allowlist"] == False:
            return True
        return sender in self.config["allowlist"]

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config
    
    async def get_room(self, room_id: RoomID) -> db.Room:
        room = await db.fetch_room(self.database, room_id)
        if room is None:
            room = db.Room(room_id)
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

        # Ignore messages that mention other users
        mentions = evt.content.get("m.mentions")
        if mentions:
            ids = mentions.get("user_ids")
            if self.client.mxid not in ids:
                await db.append_context(self.database, evt.room_id, "user", context_item_body)
                return

        # if a request is in flight, cancel it
        old_token = self.in_flight.get(evt.room_id)
        if old_token:
            old_token.cancel()
        my_token = LlmCancellationToken()
        self.in_flight[evt.room_id] = my_token
        
        context_item_body = await self.prepare_user_msg(evt.room_id, evt.sender, evt.content.body)

        room = await self.get_room(evt.room_id)
        await db.append_context(self.database, room.room_id, "user", context_item_body)
        await evt.mark_read()
        if (my_token.is_cancellation_requested()): return
        # TODO: refresh the typing indicator if generation takes longer
        # (or, alternatively, set a timeout for generation)
        try:
            backend = self.get_backend(room)
            model = room.model or backend.default_model
            system = room.system_prompt or backend.default_system_prompt
            context = await db.fetch_context(self.database, room.room_id)

            tool_cfg = self.config["tools"]

            await self.message_builder.build_with_tools(evt, self.http, self.client, self.log,
                                                        backend, model, system, context,
                                                        tool_cfg["enabled_tools"], tool_cfg["debug_messages"], my_token)
        except Exception as e:
            self.log.error(f'[maubot_llm] [handle_msg] {e}')
            raise
        finally:
            if (not my_token.is_cancellation_requested()):
                await self.client.set_typing(evt.room_id, 0)
    
    @classmethod
    def get_db_upgrade_table(cls) -> Optional[UpgradeTable]:
        return db.upgrade_table
    
    # Perform any useful transformations on the message body
    async def prepare_user_msg(self, room_id: RoomID, sender, message_body : str) -> str:
        # append the username to message, so the LLM knows who is the sender
        mems = await self.client.get_joined_members(room_id)
        member = mems.get(sender, None)
        if member:
            message_body += "\n<username>" + member.displayname + "</username>"

        return message_body
