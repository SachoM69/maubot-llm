from typing import List, Optional
from aiohttp import ClientSession

class ChatCompletion:
    def __init__(self, message: dict, finish_reason: str, model: Optional[str]) -> None:
        self.message = message
        self.finish_reason = finish_reason
        self.model = model
    
    def __eq__(self, other) -> bool:
        return self.message == other.message and self.finish_reason == other.finish_reason and self.model == other.model

class Backend:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.default_model = cfg.get("default_model")
        self.default_system_prompt = cfg.get("default_system_prompt")

    async def create_chat_completion(self, http: ClientSession,  context: List[dict], system: Optional[str] = None, model: Optional[str] = None, tools: List[dict] | None = None) -> ChatCompletion:
        raise NotImplementedError()

    async def create_chat_completion_raw(self, http: ClientSession,  context: List[dict], system: Optional[str] = None, model: Optional[str] = None, tools: List[dict] | None = None) -> dict:
        raise NotImplementedError()
    
    async def fetch_models(self, http: ClientSession) -> List[str]:
        raise NotImplementedError()