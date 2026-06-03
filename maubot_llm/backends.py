from typing import List, Optional
from aiohttp import ClientSession
import sys
from .backend_base import ChatCompletion, AsyncChatCompletion, Backend

class AsyncChatCompletionImpl(AsyncChatCompletion):
    def __init__(self, request) -> None:
        self.request = request

    def cancel(self):
        self.request.close()
        pass
    
    async def resolve(self) -> ChatCompletion:
        respbody = await self.resolve_request()
        choice = respbody["choices"][0]
        return ChatCompletion(
            message=choice["message"],
            finish_reason=choice["finish_reason"],
            model=choice.get("model", None)
        )

    async def resolve_request(self) -> dict:
        hit_except = False

        try:
            resp = await self.request.__aenter__()
            respbody = await resp.json()
            return respbody
        except:
            hit_except = True
            if not await self.request.__aexit__(*sys.exc_info()):
                raise
        finally:
            if not hit_except:
                await self.request.__aexit__(None, None, None)



class BasicOpenAIBackend(Backend):
    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self.base_url = cfg["base_url"]
        self.authorization = cfg["authorization"]
    
    def create_chat_completion(self, http: ClientSession,  context: List[dict], system: Optional[str] = None, model: Optional[str] = None, tools: Optional[List[dict]] = None) -> AsyncChatCompletion:
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
            
        return AsyncChatCompletionImpl(
            http.post(url, headers=headers, json=reqbody,)
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
