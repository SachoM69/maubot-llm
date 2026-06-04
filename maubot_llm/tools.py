import datetime
from html.parser import HTMLParser
from .tool_base import LLMTool
from .message_builder import MessageBuilder
from .cancellation_token import LlmCancellationToken

class GetDateTime(LLMTool):
    def GetName(self) -> str:
        return "get_current_datetime"
    
    def GetDescriptionDict(self) -> dict:
        return {
            "name": self.GetName(),
            "description": "Get the current date, time and timezone.",
            "parameters": {
                "properties": {},
                "type": "object"
            }
        }
    
    async def Execute(self, builder: MessageBuilder, args, token: LlmCancellationToken) -> dict:
        now = datetime.datetime.now()
        return {
            "current_timestamp": now.timestamp(),
            "current_iso": now.astimezone(datetime.timezone.utc).isoformat(),
            "user_local_iso": now.astimezone().isoformat(),
            "user_timezone": now.astimezone().tzname()
        }
    


class React(LLMTool):
    def GetName(self) -> str:
        return "react"
    
    def GetDescriptionDict(self) -> dict:
        return {
            "name": self.GetName(),
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
    
    async def Execute(self, builder: MessageBuilder, args, token: LlmCancellationToken) -> dict:
        await builder.trigger_event.react(args["key"])
        return {"status": "success", "text": "Reaction was sent successfully"}


class FetchUrl(LLMTool):
    def GetName(self) -> str:
        return "fetch_url"
    
    def GetDescriptionDict(self) -> dict:
        return {
            "name": self.GetName(),
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
    
    async def Execute(self, builder: MessageBuilder, args, token: LlmCancellationToken) -> dict:
        url = args["url"]
        html_custom_headers = {"User-Agent": "WhatsApp/2"}
        resp = await builder.http.get(url, timeout=30, headers=html_custom_headers)
        if resp.status != 200:
            result = {"error": f"{resp.status} {resp.reason}"}
        else:
            cont = await resp.text()
            parser = self.ExtractPageText()
            parser.feed(cont)
            result = {"status": "success", "text": parser.result}
        
        return result
    
    class ExtractPageText(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.result = ""
            self.current_tag = ""

        def handle_starttag(self, tag, attrs):
            self.current_tag = tag
            if tag == "meta":
                self.result += f'{str(attrs)}\n'
                
        def handle_data(self, data):
            if (self.current_tag == "script"): return
            data = data.strip()
            if len(data):
                self.result += f'{data}\n'

