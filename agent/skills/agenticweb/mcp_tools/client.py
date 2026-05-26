"""
MCP Client Adapter — AgenticWeb
Wraps each MCP tool as a LangChain BaseTool so LangGraph can call them
via standard bind_tools() / tool-calling interface.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Optional, Type
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


async def _dispatch(tool_name: str, arguments: dict) -> str:
    """In-process MCP tool dispatch (no subprocess overhead)."""
    from agent.skills.agenticweb import browser as _browser
    from agent.skills.agenticweb import scraper as _scraper
    try:
        if tool_name == "browse":
            return await _browser.navigate(arguments.get("url", ""))
        elif tool_name == "click":
            return await _browser.click(arguments.get("target", ""))
        elif tool_name == "type_text":
            return await _browser.type_text(arguments.get("selector", ""), arguments.get("text", ""))
        elif tool_name == "press_key":
            return await _browser.press_key(arguments.get("key", "Enter"))
        elif tool_name == "wait":
            return await _browser.wait(arguments.get("seconds", 2))
        elif tool_name == "page_state":
            return await _browser.page_state()
        elif tool_name == "extract":
            result = await _browser.extract(arguments.get("instruction", ""))
            return json.dumps(result) if isinstance(result, dict) else str(result)
        elif tool_name == "scrape":
            return await _scraper.scrape(arguments.get("url", ""), arguments.get("instruction", ""))
        elif tool_name == "search_web":
            results = await _scraper.search_web(arguments.get("query", ""))
            return "\n".join([f"[{i+1}] {r['title']} — {r['url']}\n    {r['snippet']}"
                              for i, r in enumerate(results)])
        return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Tool error ({tool_name}): {e}"


class MCPTool(BaseTool):
    name: str
    description: str
    mcp_tool_name: str
    args_schema: Optional[Type[BaseModel]] = None

    def _run(self, **kwargs: Any) -> str:
        return asyncio.get_event_loop().run_until_complete(self._arun(**kwargs))

    async def _arun(self, **kwargs: Any) -> str:
        return await _dispatch(self.mcp_tool_name, kwargs)


def get_mcp_tools() -> list[BaseTool]:
    """Return all MCP tools as LangChain BaseTool objects for LangGraph."""

    class BrowseInput(BaseModel):
        url: str = Field(description="Full URL to navigate to")

    class ClickInput(BaseModel):
        target: str = Field(description="Visible text or CSS selector to click")

    class TypeInput(BaseModel):
        selector: str = Field(description="CSS selector or placeholder of input")
        text: str = Field(description="Text to type")

    class ExtractInput(BaseModel):
        instruction: str = Field(description="What to extract from the current page")

    class PressKeyInput(BaseModel):
        key: str = Field(description="Keyboard key to press, such as Enter, Escape, Tab, ArrowDown")

    class WaitInput(BaseModel):
        seconds: float = Field(default=2, description="Seconds to wait before reading the page again")

    class PageStateInput(BaseModel):
        pass

    class ScrapeInput(BaseModel):
        url: str = Field(description="URL to scrape")
        instruction: str = Field(default="", description="What to extract")

    class SearchInput(BaseModel):
        query: str = Field(description="Web search query")

    return [
        MCPTool(name="browse",      description="Navigate to URL with real browser. Use for JS-heavy sites.", mcp_tool_name="browse",      args_schema=BrowseInput),
        MCPTool(name="click",       description="Click button or link on current page by text or selector.",  mcp_tool_name="click",       args_schema=ClickInput),
        MCPTool(name="type_text",   description="Type text into an input field on current page.",             mcp_tool_name="type_text",   args_schema=TypeInput),
        MCPTool(name="press_key",   description="Press a keyboard key in the live browser.",                  mcp_tool_name="press_key",   args_schema=PressKeyInput),
        MCPTool(name="wait",        description="Wait for page updates, then return current page state.",     mcp_tool_name="wait",        args_schema=WaitInput),
        MCPTool(name="page_state",  description="Read current live browser title, URL, and visible text.",    mcp_tool_name="page_state",  args_schema=PageStateInput),
        MCPTool(name="extract",     description="Extract structured data from current browser page with AI.", mcp_tool_name="extract",     args_schema=ExtractInput),
        MCPTool(name="scrape",      description="Fast HTTP fetch + extract. Best for static pages.",          mcp_tool_name="scrape",      args_schema=ScrapeInput),
        MCPTool(name="search_web",  description="DuckDuckGo search. Returns top 5 results with URLs.",        mcp_tool_name="search_web",  args_schema=SearchInput),
    ]
