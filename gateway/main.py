"""
AgenticWeb Gateway
==================
The control plane. Owns:
  - WebSocket connections (Web UI clients)
  - REST API (extension, external callers)
  - Telegram bot listener
  - Session registry
  - Message routing: channel → agent → channel

No OpenClaw dependency. Built from scratch.

Endpoints:
  WS   /ws/{session_id}          ← Web UI connects here
  POST /api/chat                 ← Extension / REST callers
  GET  /api/sessions             ← list active sessions
  GET  /api/health               ← health check
  GET  /api/providers            ← available LLM providers
  POST /telegram/webhook         ← Telegram webhook (set by bot setup)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.skills.agenticweb.agent_loop import run_agent
from agent.skills.agenticweb.llm_router import LLMRouter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

AGENT_URL = f"http://localhost:{os.getenv('AGENT_PORT', '8765')}"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ── Session registry ──────────────────────────────────────────────────────────

class Session:
    """One user session — tracks WS connection + message history."""
    def __init__(self, session_id: str, channel: str = "web"):
        self.session_id = session_id
        self.channel = channel          # "web" | "telegram" | "extension"
        self.ws: Optional[WebSocket] = None
        self.telegram_chat_id: Optional[int] = None
        self.history: list[dict] = []
        self.provider: str = os.getenv("AGENT_PROVIDER", "gemini")
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None

    async def send(self, event: dict):
        """Send event to this session's channel."""
        if self.channel == "web" and self.ws:
            try:
                await self.ws.send_text(json.dumps(event))
            except Exception:
                pass
        elif self.channel == "telegram" and self.telegram_chat_id:
            await telegram_send(self.telegram_chat_id, _format_telegram(event))

    async def cancel(self, reason: str = "Cancelled by user") -> bool:
        if self.task and not self.task.done():
            self.task.cancel()
            self.running = False
            await self.send({"type": "cancelled", "message": reason})
            return True
        self.running = False
        return False


class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, session_id: str, channel: str = "web") -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id, channel)
        return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def all(self) -> list[Session]:
        return list(self._sessions.values())

    def remove(self, session_id: str):
        self._sessions.pop(session_id, None)


registry = SessionRegistry()


# ── Lifespan (startup/shutdown) ───────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Telegram webhook on startup if token provided
    if TELEGRAM_TOKEN:
        asyncio.create_task(_setup_telegram())
    yield
    # Cleanup browser on shutdown
    from agent.skills.agenticweb.browser import close_browser
    await close_browser()


app = FastAPI(title="AgenticWeb Gateway", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket endpoint (Web UI) ───────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = registry.get_or_create(session_id, channel="web")
    session.ws = websocket
    logger.info(f"WS connected: {session_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)

            if msg.get("type") == "chat":
                goal = msg.get("content", "").strip()
                provider = msg.get("provider", session.provider)
                if goal.lower() in {"/stop", "stop", "cancel"}:
                    await session.cancel()
                    continue
                if goal and not session.running:
                    session.provider = provider
                    session.task = asyncio.create_task(_run_agent_task(session, goal))
                elif goal and session.running:
                    await session.send({"type": "status", "message": "Already running. Use Stop to cancel first."})

            elif msg.get("type") == "set_provider":
                session.provider = msg.get("provider", session.provider)
                await session.send({"type": "system", "message": f"Provider set to {session.provider}"})

            elif msg.get("type") == "stop":
                await session.cancel()

            elif msg.get("type") == "ping":
                await session.send({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: {session_id}")
        session.ws = None
    except Exception as e:
        logger.error(f"WS error {session_id}: {e}")


# ── REST endpoint (Extension + external) ─────────────────────────────────────

class ChatRequest(BaseModel):
    goal: str
    session_id: Optional[str] = None
    provider: Optional[str] = None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    Run agent task. Streams SSE events.
    Used by Chrome extension and external callers.
    """
    if not req.goal.strip():
        raise HTTPException(400, "goal cannot be empty")

    session_id = req.session_id or str(uuid.uuid4())[:8]
    session = registry.get_or_create(session_id, channel="extension")
    if req.provider:
        session.provider = req.provider

    from sse_starlette.sse import EventSourceResponse

    async def event_gen():
        async for event in run_agent(
            goal=req.goal,
            session_id=session_id,
            provider=session.provider,
        ):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_gen())


@app.get("/api/health")
async def health():
    router = LLMRouter()
    return {
        "status": "ok",
        "version": "1.0.0",
        "channels": {
            "web": True,
            "telegram": bool(TELEGRAM_TOKEN),
            "extension": True,
        },
        "stack": {
            "agent_framework": "LangGraph 0.2",
            "tool_protocol":   "MCP 1.1",
            "gateway":         "custom FastAPI",
        },
        "providers": {
            "available": router.available_providers(),
            "default": os.getenv("AGENT_PROVIDER", "gemini"),
        },
        "active_sessions": len(registry.all()),
    }


@app.get("/api/sessions")
async def sessions():
    return {
        "sessions": [
            {
                "id": s.session_id,
                "channel": s.channel,
                "provider": s.provider,
                "running": s.running,
            }
            for s in registry.all()
        ]
    }


@app.post("/api/sessions/{session_id}/cancel")
async def cancel_session(session_id: str):
    session = registry.get(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    cancelled = await session.cancel()
    return {"ok": True, "session_id": session_id, "cancelled": cancelled}


@app.get("/api/providers")
async def providers():
    router = LLMRouter()
    return {
        "default": os.getenv("AGENT_PROVIDER", "gemini"),
        "available": router.available_providers(),
        "all": [
            {"id": "openrouter_qwen", "name": "OpenRouter Qwen3 Next Free", "free": True},
            {"id": "openrouter_qwen_coder", "name": "OpenRouter Qwen3 Coder Free", "free": True},
            {"id": "openrouter_deepseek", "name": "OpenRouter DeepSeek V4 Flash Free", "free": True},
            {"id": "openrouter_fast", "name": "OpenRouter Nemotron Nano 9B Free", "free": True},
            {"id": "openrouter_nemotron", "name": "OpenRouter Nemotron Nano 30B Free", "free": True},
            {"id": "openrouter_glm", "name": "OpenRouter GLM 4.5 Air Free", "free": True},
            {"id": "openrouter_llama", "name": "OpenRouter Llama 3.3 70B Free", "free": True},
            {"id": "openrouter_gptoss", "name": "OpenRouter GPT OSS 20B Free", "free": True},
            {"id": "openrouter_gemma", "name": "OpenRouter Gemma 4 31B Free", "free": True},
            {"id": "openrouter_minimax", "name": "OpenRouter MiniMax M2.5 Free", "free": True},
            {"id": "openrouter_free", "name": "OpenRouter Free Router", "free": True},
            {"id": "openrouter_kimi", "name": "OpenRouter Kimi K2 Thinking", "free": False},
            {"id": "openrouter", "name": "OpenRouter Custom Model", "free": True},
            {"id": "azure_openai", "name": "Azure OpenAI (Microsoft Stack)", "free": False},
            {"id": "gemini",   "name": "Gemma 4 31B IT",     "free": True},
            {"id": "groq",     "name": "Groq Llama 3.3 70B", "free": True},
            {"id": "deepseek", "name": "DeepSeek V4 Flash",    "free": False},
            {"id": "claude",   "name": "Claude Sonnet",       "free": False},
            {"id": "openai",   "name": "GPT-4o Mini",         "free": False},
        ],
    }


# ── Telegram webhook ──────────────────────────────────────────────────────────

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Telegram sends updates here."""
    body = await request.json()
    message = body.get("message") or body.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", str(chat_id))

    if not text:
        return JSONResponse({"ok": True})

    # Handle commands
    if text == "/start":
        await telegram_send(chat_id,
            "👋 *AgenticWeb* — autonomous web agent\n\n"
            "Just type your goal and I'll browse the web to complete it.\n\n"
            "Examples:\n"
            "• Find cheapest flight BLR to GOI this Friday\n"
            "• What's the gold price in India today?\n"
            "• Summarise top HackerNews stories\n\n"
            "Commands: /start /status /provider gemini|groq|deepseek|claude|openai"
        )
        return JSONResponse({"ok": True})

    if text == "/status":
        session = registry.get(str(chat_id))
        provider = session.provider if session else os.getenv("AGENT_PROVIDER", "gemini")
        running = session.running if session else False
        await telegram_send(chat_id,
            f"{'🔄 Running' if running else '✅ Ready'} · Provider: `{provider}`"
        )
        return JSONResponse({"ok": True})

    if text in {"/stop", "/cancel"}:
        session = registry.get(str(chat_id))
        if session:
            await session.cancel("Cancelled from Telegram")
            await telegram_send(chat_id, "Stopped current task.")
        else:
            await telegram_send(chat_id, "No active task.")
        return JSONResponse({"ok": True})

    if text.startswith("/provider "):
        p = text.split("/provider ", 1)[1].strip()
        session = registry.get_or_create(str(chat_id), channel="telegram")
        session.provider = p
        session.telegram_chat_id = chat_id
        await telegram_send(chat_id, f"✅ Provider set to `{p}`")
        return JSONResponse({"ok": True})

    # Regular message → run agent
    session = registry.get_or_create(str(chat_id), channel="telegram")
    session.telegram_chat_id = chat_id

    if session.running:
        await telegram_send(chat_id, "⏳ Still working on your previous task...")
        return JSONResponse({"ok": True})

    session.task = asyncio.create_task(_run_agent_task(session, text))
    await telegram_send(chat_id, "🌐 Working on it...")
    return JSONResponse({"ok": True})


# ── Internal agent runner ─────────────────────────────────────────────────────

async def _run_agent_task(session: Session, goal: str):
    """Run the agent and stream events to the session's channel."""
    session.running = True
    try:
        async for event in run_agent(
            goal=goal,
            session_id=session.session_id,
            provider=session.provider,
        ):
            await session.send(event)
    except asyncio.CancelledError:
        logger.info(f"Agent task cancelled for {session.session_id}")
        await session.send({"type": "cancelled", "message": "Cancelled by user"})
        raise
    except Exception as e:
        logger.exception(f"Agent task error for {session.session_id}")
        await session.send({"type": "error", "message": str(e)})
    finally:
        session.running = False
        session.task = None


# ── Telegram helpers ──────────────────────────────────────────────────────────

async def telegram_send(chat_id: int, text: str):
    """Send a message to a Telegram chat."""
    if not TELEGRAM_TOKEN:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:4096],   # Telegram limit
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


def _format_telegram(event: dict) -> str:
    """Format agent event for Telegram."""
    t = event.get("type")
    if t == "status":
        return f"⚙ _{event.get('message', '')}_"
    elif t == "step":
        return f"✓ Step {event.get('step')}: {event.get('tool')} → {event.get('result', '')[:120]}"
    elif t == "done":
        return f"✅ *Done*\n\n{event.get('result', '')}"
    elif t == "error":
        return f"❌ Error: {event.get('message', '')}"
    return ""


async def _setup_telegram():
    """Register webhook with Telegram (called on startup if token set)."""
    await asyncio.sleep(2)   # let server start
    logger.info("Telegram token found — set webhook manually:")
    logger.info(f"  curl '{TELEGRAM_API}/setWebhook?url=https://YOUR_DOMAIN/telegram/webhook'")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("GATEWAY_PORT", "8000"))
    logger.info(f"AgenticWeb Gateway starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
