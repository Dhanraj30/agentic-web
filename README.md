# 🌐 AgenticWeb

> Autonomous web agent platform — **no OpenClaw, no third-party gateway**
> Built ground-up · LangGraph · MCP · React · Microsoft Build Hackathon 2025

---

## What it is

AgenticWeb is a complete platform (not a plugin) that lets users delegate web tasks to an AI agent via three channels:

| Channel | URL / Access |
|---|---|
| **Web UI** | `http://localhost:3000` — React chat interface |
| **Telegram** | Your bot (set `TELEGRAM_BOT_TOKEN`) |
| **Chrome Extension** | Load `extension/` in dev mode |

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                   Channels                           │
│  React Web UI (:3000)  Telegram Bot  Chrome Ext     │
└──────────────┬───────────────┬──────────────────────┘
               │ WebSocket     │ HTTP/SSE
               ▼               ▼
┌──────────────────────────────┐
│   Gateway  gateway/main.py  │  :8000
│   FastAPI + WebSocket        │
│   Session registry           │
│   Telegram webhook handler   │
└──────────────┬───────────────┘
               │ in-process
               ▼
┌──────────────────────────────┐
│   LangGraph Agent Loop       │  agent/skills/agenticweb/
│   ACT → OBSERVE → SUMMARISE │
└──────────────┬───────────────┘
               │ MCP calls
               ▼
┌──────────────────────────────┐
│   MCP Tool Server (MCP 1.1) │  mcp_tools/server.py
│   browse · scrape · search  │
│   click · type · extract    │
└──────────────┬───────────────┘
               │
               ▼
        🌐 The Real Web
```

---

## Quick Start

```bash
cp .env.example .env
# Add GEMINI_API_KEY= (free at aistudio.google.com/apikey)

chmod +x scripts/*.sh
./scripts/start.sh
```

Open `http://localhost:3000` and type a goal.

---

## Providers

| Provider | Key | Free |
|---|---|---|
| `gemini` (default) | `GEMINI_API_KEY` | ✅ |
| `openrouter_qwen` | `OPENROUTER_API_KEY` | ✅ |
| `openrouter_deepseek` | `OPENROUTER_API_KEY` | ✅ |
| `openrouter_free` | `OPENROUTER_API_KEY` | ✅ |
| `openrouter_auto` | `OPENROUTER_API_KEY` | paid, auto-routed |
| `openrouter_kimi` | `OPENROUTER_API_KEY` | paid |
| `groq` | `GROQ_API_KEY` | ✅ |
| `deepseek` | `DEEPSEEK_API_KEY` | cheap |
| `claude` | `ANTHROPIC_API_KEY` | paid |
| `openai` | `OPENAI_API_KEY` | paid |

---

## Project Structure

```
agenticweb/
├── .env.example
├── README.md
├── ARCHITECTURE.md
├── gateway/
│   └── main.py          ← FastAPI gateway (WS + REST + Telegram)
├── agent/
│   ├── server.py        ← Agent FastAPI server (:8765)
│   ├── requirements.txt
│   └── skills/agenticweb/
│       ├── agent_loop.py    ← LangGraph state machine
│       ├── llm_router.py    ← multi-provider LLM
│       ├── browser.py       ← Playwright tools
│       ├── scraper.py       ← httpx + BS4 + search
│       ├── memory.py        ← SQLite
│       └── mcp_tools/
│           ├── server.py    ← MCP Server (stdio)
│           └── client.py    ← MCP→LangChain adapter
├── web/                 ← React + Vite + Tailwind UI
├── extension/           ← Chrome MV3 extension
├── scripts/
│   ├── start.sh
│   └── stop.sh
└── docs/
```

---

## API

```bash
# Health
curl http://localhost:8765/health

# Run agent task (SSE stream)
curl -N -X POST http://localhost:8765/run \
  -H "Content-Type: application/json" \
  -d '{"goal":"find gold price India today","provider":"gemini"}'

# List MCP tools
curl http://localhost:8765/mcp-tools

# LangGraph topology
curl http://localhost:8765/graph

# Cancel a running web session
curl -X POST http://localhost:8000/api/sessions/<session_id>/cancel
```

Operator controls:
- Web UI: press the red stop button while a task is running
- WebSocket: send `{"type":"stop"}`
- Telegram: send `/stop` or `/cancel`

---

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — full system design
- [docs/SETUP.md](docs/SETUP.md) — detailed setup
- [docs/TELEGRAM.md](docs/TELEGRAM.md) — Telegram bot setup
- [docs/EXTENSION.md](docs/EXTENSION.md) — Chrome extension
- [docs/PROVIDERS.md](docs/PROVIDERS.md) — LLM providers
