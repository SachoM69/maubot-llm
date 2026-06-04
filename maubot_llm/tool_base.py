from .cancellation_token import LlmCancellationToken

class LLMTool:
    def GetName(self) -> str:
        raise NotImplementedError()
    
    def GetDescriptionDict(self) -> dict:
        raise NotImplementedError()
    
    async def Execute(self, message_builder, args, token: LlmCancellationToken) -> dict:
        raise NotImplementedError()