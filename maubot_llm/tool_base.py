from maubot import MessageEvent
from aiohttp import ClientSession
from .cancellation_token import LlmCancellationToken

class LLMTool:
    def GetName(self) -> str:
        raise NotImplementedError()
    
    def GetDescriptionDict(self) -> dict:
        raise NotImplementedError()
    
    async def Execute(self, evt: MessageEvent, http: ClientSession, args, token: LlmCancellationToken) -> dict:
        raise NotImplementedError()