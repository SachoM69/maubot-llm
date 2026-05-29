from maubot import Plugin
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command, event
from mautrix.types import EventType, MessageEvent
from typing import Type
from maubot_llm.backends import Backend, BasicOpenAIBackend
from maubot_llm import db
from mautrix.util.async_db import UpgradeTable


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("allowlist")
        helper.copy("default_backend")
        helper.copy("backends")


class LlmBot(Plugin):
    async def start(self) -> None:
        self.config.load_and_update()
    
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
            msg = f"Invalid backend. Available backends: {all_backends}"
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
        if prompt == "-":
            room.system_prompt = None
        else:
            room.system_prompt = prompt
        await db.upsert_room(self.database, room)
        await evt.react("✅")

    @llm_command.subcommand(help="Forget all context and treat subsequent messages as part of a new chat with the LLM.")
    async def clear(self, evt: MessageEvent) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        await db.clear_context(self.database, evt.room_id)
        await evt.react("✅")

    @event.on(EventType.ROOM_MESSAGE)
    async def handle_msg(self, evt: MessageEvent) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        if evt.content.body.startswith("!"):
            return
        room = await self.get_room(evt.room_id)
        await db.append_context(self.database, room.room_id, "user", evt.content.body)
        await evt.mark_read()
        # TODO: refresh the typing indicator if generation takes longer
        # (or, alternatively, set a timeout for generation)
        await self.client.set_typing(evt.room_id, 30000)
        try:
            backend = self.get_backend(room)
            model = room.model or backend.default_model
            system = room.system_prompt or backend.default_system_prompt
            context = await db.fetch_context(self.database, room.room_id)
            completion = await backend.create_chat_completion(self.http, context=context, system=system, model=model)
            await db.append_context(self.database, room.room_id, completion.message["role"], completion.message["content"])
            await evt.respond(completion.message["content"])
        finally:
            await self.client.set_typing(evt.room_id, 0)
    
    @classmethod
    def get_db_upgrade_table(cls) -> UpgradeTable | None:
        return db.upgrade_table
