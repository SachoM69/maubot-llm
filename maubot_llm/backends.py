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

    async def create_chat_completion(self, http: ClientSession,  context: List[dict], system: Optional[str] = None, model: Optional[str] = None) -> ChatCompletion:
        raise NotImplementedError()
    
    async def fetch_models(self, http: ClientSession) -> List[str]:
        raise NotImplementedError()


class BasicOpenAIBackend(Backend):
    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self.base_url = cfg["base_url"]
        self.authorization = cfg["authorization"]
    
    async def create_chat_completion(self, http: ClientSession,  context: List[dict], system: Optional[str] = None, model: Optional[str] = None) -> ChatCompletion:
        url = f"{self.base_url}/v1/chat/completions"
        reqbody = {"messages": context}
        if system is not None:
            reqbody["messages"].insert(0, {"role": "system", "content": system})
        if model is not None:
            reqbody["model"] = model
        headers = {}
        if self.authorization is not None:
            headers["Authorization"] = self.authorization
        async with http.post(url, headers=headers, json=reqbody) as resp:
            # TODO error handling
            respbody = await resp.json()
            choice = respbody["choices"][0]
            return ChatCompletion(
                message=choice["message"],
                finish_reason=choice["finish_reason"],
                model=choice.get("model", None)
            )
    
    async def fetch_models(self, http: ClientSession) -> List[str]:
        url = f"{self.base_url}/v1/models"
        headers = {}
        if self.authorization is not None:
            headers["Authorization"] = self.authorization
        async with http.get(url, headers=headers) as resp:
            # TODO error handling
            respbody = await resp.json()
            return [m["id"] for m in respbody["data"]]
