from typing import List, Optional
from aiohttp import ClientSession
import asyncio
import sys
from .backend_base import ChatCompletion, Backend

class BasicOpenAIBackend(Backend):
    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self.base_url = cfg["base_url"]
        self.authorization = cfg["authorization"]
    
    async def create_chat_completion(self, http: ClientSession,  context: List[dict], system: Optional[str] = None, model: Optional[str] = None, tools: Optional[List[dict]] = None) -> ChatCompletion:
        respbody = await self.create_chat_completion_raw(http, context, system, model, tools)
        choice = respbody["choices"][0]
        return ChatCompletion(
            message=choice["message"],
            finish_reason=choice["finish_reason"],
            model=choice.get("model", None)
        )
    
    async def create_chat_completion_raw(self, http: ClientSession,  context: List[dict], system: Optional[str] = None, model: Optional[str] = None, tools: Optional[List[dict]] = None) -> dict:
        url = f"{self.base_url}/v1/chat/completions"
        reqbody = {"messages": context}
        if system is not None:
            reqbody["messages"].insert(0, {"role": "system", "content": system})
        if model is not None:
            reqbody["model"] = model
        if tools is not None:
            reqbody["tools"] = tools
        headers = {}
        if self.authorization is not None:
            headers["Authorization"] = self.authorization
            
        async with http.post(url, headers=headers, json=reqbody) as resp:
            respbody = await resp.json()
            return respbody
    
    async def fetch_models(self, http: ClientSession) -> List[str]:
        url = f"{self.base_url}/v1/models"
        headers = {}
        if self.authorization is not None:
            headers["Authorization"] = self.authorization
        async with http.get(url, headers=headers) as resp:
            # TODO error handling
            respbody = await resp.json()
            return [m["id"] for m in respbody["data"]]
