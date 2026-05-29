"""
AgenticWeb Agent Server  — :8765
Exposes the LangGraph agent + MCP tool info via REST/SSE.
Called by the Gateway (and directly by the extension for SSE streaming).
"""
from __future__ import annotations
import json, logging, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from skills.agenticweb.agent_loop import run_agent
from skills.agenticweb.agent_loop import context_manager
from skills.agenticweb.llm_router import LLMRouter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AgenticWeb Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class RunRequest(BaseModel):
    goal: str
    session_id: str | None = None
    provider: str | None = None


@app.post("/run")
async def run(req: RunRequest):
    if not req.goal.strip():
        raise HTTPException(400, "goal cannot be empty")
    async def gen():
        async for event in run_agent(req.goal, req.session_id, req.provider):
            yield {"data": json.dumps(event)}
    return EventSourceResponse(gen())


@app.get("/health")
async def health():
    r = LLMRouter()
    return {
        "status": "ok", "version": "1.0.0",
        "stack": {"agent_framework": "LangGraph 0.2", "tool_protocol": "MCP 1.1"},
        "providers": {"available": r.available_providers(), "default": os.getenv("AGENT_PROVIDER","gemini")},
    }


@app.get("/providers")
async def providers():
    r = LLMRouter()
    return {
        "default": os.getenv("AGENT_PROVIDER","gemini"),
        "available": r.available_providers(),
        "all": [
            {"id":"openrouter_qwen", "name":"OpenRouter Qwen3 Next Free", "free": True},
            {"id":"openrouter_qwen_coder", "name":"OpenRouter Qwen3 Coder Free", "free": True},
            {"id":"openrouter_deepseek", "name":"OpenRouter DeepSeek V4 Flash Free", "free": True},
            {"id":"openrouter_fast", "name":"OpenRouter Nemotron Nano 9B Free", "free": True},
            {"id":"openrouter_nemotron", "name":"OpenRouter Nemotron Nano 30B Free", "free": True},
            {"id":"openrouter_glm", "name":"OpenRouter GLM 4.5 Air Free", "free": True},
            {"id":"openrouter_llama", "name":"OpenRouter Llama 3.3 70B Free", "free": True},
            {"id":"openrouter_gptoss", "name":"OpenRouter GPT OSS 20B Free", "free": True},
            {"id":"openrouter_gemma", "name":"OpenRouter Gemma 4 31B Free", "free": True},
            {"id":"openrouter_minimax", "name":"OpenRouter MiniMax M2.5 Free", "free": True},
            {"id":"openrouter_free", "name":"OpenRouter Free Router", "free": True},
            {"id":"openrouter_auto", "name":"OpenRouter Auto Router", "free": False},
            {"id":"openrouter_kimi", "name":"OpenRouter Kimi K2 Thinking", "free": False},
            {"id":"openrouter", "name":"OpenRouter Custom Model", "free": False},
            {"id":"gemini",   "name":"Gemma 4 31B IT",     "free": True},
            {"id":"groq",     "name":"Groq Llama 3.3 70B", "free": True},
            {"id":"deepseek", "name":"DeepSeek V4 Flash",    "free": False},
            {"id":"claude",   "name":"Claude Sonnet",       "free": False},
            {"id":"openai",   "name":"GPT-4o Mini",         "free": False},
        ],
    }


@app.get("/debug/context/{session_id}")
async def debug_context(session_id: str):
    context = context_manager.as_dict(session_id)
    if not context:
        raise HTTPException(404, "context not found in this process")
    return context


@app.get("/graph")
async def graph():
    return {
        "framework": "LangGraph 0.2",
        "nodes": ["act","observe","summarise"],
        "edges": [
            {"from":"act","to":"observe","condition":"has tool_calls"},
            {"from":"act","to":"summarise","condition":"no tool_calls or max_iter"},
            {"from":"observe","to":"act","condition":"always"},
            {"from":"summarise","to":"END","condition":"always"},
        ],
        "tools_protocol": "MCP 1.1",
        "max_iterations": 12,
    }


@app.get("/mcp-tools")
async def mcp_tools():
    from skills.agenticweb.mcp_tools.client import get_mcp_tools
    return {"protocol":"MCP 1.1", "tools":[{"name":t.name,"description":t.description} for t in get_mcp_tools()]}


if __name__ == "__main__":
    port = int(os.getenv("AGENT_PORT","8765"))
    logger.info(f"Agent server starting on :{port}")
    uvicorn.run(app, host="localhost", port=port)
