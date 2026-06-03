from maubot import MessageEvent
from aiohttp import ClientSession

class LLMTool:
    def GetName(self) -> str:
        raise NotImplementedError()
    
    def GetDescriptionDict(self) -> dict:
        raise NotImplementedError()
    
    async def Execute(self, evt: MessageEvent, http: ClientSession, args) -> dict:
        raise NotImplementedError()