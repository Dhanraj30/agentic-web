"""
MCP Tool Server — AgenticWeb
Exposes all agent tools via the Model Context Protocol (MCP 1.1).
Transport: stdio (standard) — can be connected by any MCP client.

Run standalone:
    python -m agent.skills.agenticweb.mcp_tools.server
"""
from __future__ import annotations
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

from agent.skills.agenticweb import browser as _browser
from agent.skills.agenticweb import scraper as _scraper

logger = logging.getLogger(__name__)
mcp = Server("agenticweb-tools")


@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="browse", description="Navigate to URL with real browser (JS rendered).",
             inputSchema={"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}),
        Tool(name="click", description="Click element on current page by text or CSS selector.",
             inputSchema={"type":"object","properties":{"target":{"type":"string"}},"required":["target"]}),
        Tool(name="type_text", description="Type text into input field.",
             inputSchema={"type":"object","properties":{"selector":{"type":"string"},"text":{"type":"string"}},"required":["selector","text"]}),
        Tool(name="press_key", description="Press a keyboard key in the live browser.",
             inputSchema={"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}),
        Tool(name="wait", description="Wait for page updates and return current page state.",
             inputSchema={"type":"object","properties":{"seconds":{"type":"number","default":2}}}),
        Tool(name="page_state", description="Read current live browser title, URL, and visible text.",
             inputSchema={"type":"object","properties":{}}),
        Tool(name="extract", description="Extract structured data from current browser page using AI.",
             inputSchema={"type":"object","properties":{"instruction":{"type":"string"}},"required":["instruction"]}),
        Tool(name="scrape", description="Fast HTTP fetch and extract from static page.",
             inputSchema={"type":"object","properties":{"url":{"type":"string"},"instruction":{"type":"string"}},"required":["url"]}),
        Tool(name="search_web", description="Search web via DuckDuckGo. Returns top 5 results.",
             inputSchema={"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}),
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        if name == "browse":
            r = await _browser.navigate(arguments["url"])
        elif name == "click":
            r = await _browser.click(arguments["target"])
        elif name == "type_text":
            r = await _browser.type_text(arguments["selector"], arguments["text"])
        elif name == "press_key":
            r = await _browser.press_key(arguments["key"])
        elif name == "wait":
            r = await _browser.wait(arguments.get("seconds", 2))
        elif name == "page_state":
            r = await _browser.page_state()
        elif name == "extract":
            r = str(await _browser.extract(arguments["instruction"]))
        elif name == "scrape":
            r = await _scraper.scrape(arguments["url"], arguments.get("instruction", ""))
        elif name == "search_web":
            results = await _scraper.search_web(arguments["query"])
            r = "\n".join([f"[{i+1}] {x['title']}\n    {x['url']}\n    {x['snippet']}"
                           for i, x in enumerate(results)])
        else:
            return CallToolResult(content=[TextContent(type="text", text=f"Unknown tool: {name}")], isError=True)
        return CallToolResult(content=[TextContent(type="text", text=str(r))])
    except Exception as e:
        logger.exception(f"Tool {name} failed")
        return CallToolResult(content=[TextContent(type="text", text=f"Error: {e}")], isError=True)


async def run_stdio():
    async with stdio_server() as (r, w):
        await mcp.run(r, w, mcp.create_initialization_options())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_stdio())
