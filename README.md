# AgenticWeb

Autonomous web-agent platform built from the ground up with FastAPI, LangGraph, MCP-style tools, Playwright, SQLite memory, and a React web interface.

AgenticWeb lets a user give a web task once, then streams the agent's search, scraping, browser actions, screenshots, and final grounded answer back through the web UI, REST/SSE, Telegram, or a Chrome extension.

## What It Does

- Runs an autonomous ACT -> OBSERVE -> SUMMARISE agent loop.
- Searches the web with DuckDuckGo HTML search.
- Scrapes static pages quickly with `httpx` and BeautifulSoup.
- Uses Playwright Chromium for JS-heavy pages and interaction.
- Streams live browser screenshots to the UI as Canvas events.
- Supports multiple LLM providers with fallback and cooldown.
- Persists sessions, step logs, facts, summaries, context notes, and references in SQLite.
- Exposes both a gateway API and a direct agent API.
- Supports WebSocket, SSE, Telegram webhook, and Chrome extension clients.

## Channels

| Channel | Access |
|---|---|
| Web UI | `http://localhost:3000` |
| Gateway REST/SSE | `POST http://localhost:8000/api/chat` |
| Agent REST/SSE | `POST http://localhost:8765/run` |
| Telegram | Set `TELEGRAM_BOT_TOKEN` and configure webhook |
| Chrome Extension | Load `extension/` in Chrome developer mode |

## Architecture Snapshot

```text
React UI / Extension / Telegram / REST client
        |
        v
FastAPI Gateway - gateway/main.py
  - WebSocket
  - REST/SSE
  - Telegram webhook
  - Session registry
        |
        v
LangGraph Agent - agent/skills/agenticweb/agent_loop.py
  - ACT
  - OBSERVE
  - SUMMARISE
  - Provider fallback
  - Context and memory
        |
        v
Tool Layer
  - MCP/LangChain adapter
  - Playwright browser tools
  - Search and scrape tools
        |
        v
The live web + SQLite memory
```

For the detailed system design, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- Python 3.10+
- Node.js 18+
- npm
- Playwright Chromium dependencies
- At least one LLM provider key or token

Recommended free-ish starting providers:

- `GITHUB_TOKEN` for GitHub Models if enabled on your account.
- `GEMINI_API_KEY` from Google AI Studio.
- `GROQ_API_KEY` from Groq.
- `OPENROUTER_API_KEY` for OpenRouter free models.

## Quick Start

```bash
cp .env.example .env
```

Edit `.env` and add at least one provider key. Then start everything:

```bash
chmod +x scripts/*.sh
./scripts/start.sh
```

Open:

```text
http://localhost:3000
```

Stop services:

```bash
./scripts/stop.sh
```

## Manual Start

Use this if you are on Windows PowerShell or prefer separate terminals.

### 1. Backend Environment

```powershell
cd agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### 2. Agent API

```powershell
cd agent
.\.venv\Scripts\Activate.ps1
python server.py
```

Runs on:

```text
http://localhost:8765
```

### 3. Gateway

In another terminal:

```powershell
.\agent\.venv\Scripts\Activate.ps1
python gateway\main.py
```

Runs on:

```text
http://localhost:8000
```

### 4. Web UI

In another terminal:

```powershell
cd web
npm install
npm run dev
```

Runs on:

```text
http://localhost:3000
```

## Environment

Copy `.env.example` to `.env` and fill only what you use.

Important variables:

| Variable | Purpose |
|---|---|
| `AGENT_PROVIDER` | Default provider, for example `github`, `gemini`, `groq`, `openrouter_qwen` |
| `AGENT_MAX_ITERATIONS` | Max ACT loop iterations |
| `LLM_CALL_TIMEOUT_SECONDS` | Timeout for each provider call |
| `GATEWAY_PORT` | Gateway port, default `8000` |
| `AGENT_PORT` | Agent API port, default `8765` |
| `TELEGRAM_BOT_TOKEN` | Enables Telegram bot webhook flow |
| `BROWSER_HEADLESS` | Run browser headless or visible |
| `BROWSER_SLOW_MO_MS` | Slow down browser actions for debugging |

Provider keys:

| Provider | Env vars |
|---|---|
| GitHub Models | `GITHUB_TOKEN`, `GITHUB_MODEL` |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| Groq | `GROQ_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Anthropic Claude | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` |

Do not commit `.env`.

## Providers

Common provider ids:

| Provider ID | Notes |
|---|---|
| `github` | GitHub Models / Microsoft stack |
| `gemini` | Gemini/Gemma via Google provider config |
| `groq` | Groq-hosted Llama model |
| `deepseek` | DeepSeek chat model |
| `claude` | Anthropic Claude |
| `openai` | OpenAI GPT model |
| `azure_openai` | Azure OpenAI deployment |
| `openrouter_qwen` | OpenRouter Qwen free model |
| `openrouter_qwen_coder` | OpenRouter Qwen Coder free model |
| `openrouter_deepseek` | OpenRouter DeepSeek free model |
| `openrouter_fast` | OpenRouter fast free model |
| `openrouter_free` | OpenRouter free router |
| `openrouter_auto` | OpenRouter auto router, may select paid models |
| `openrouter_kimi` | OpenRouter Kimi paid model |

The agent records provider failures in cooldown state and tries fallback providers when rate limits, quota, billing, server, timeout, or tool-routing failures occur.

## Project Structure

```text
agenticweb/
  .env.example
  README.md
  ARCHITECTURE.md
  gateway/
    main.py
  agent/
    server.py
    requirements.txt
    data/
      memory.db
      cooldown_state.json
    skills/agenticweb/
      agent_loop.py
      browser.py
      context_manager.py
      cooldown.py
      llm_router.py
      memory.py
      scraper.py
      mcp_tools/
        client.py
        server.py
  web/
    package.json
    src/
  extension/
  scripts/
    start.sh
    stop.sh
  docs/
```

## API Usage

Agent health:

```bash
curl http://localhost:8765/health
```

Gateway health:

```bash
curl http://localhost:8000/api/health
```

Run an agent task through the direct agent API:

```bash
curl -N -X POST http://localhost:8765/run \
  -H "Content-Type: application/json" \
  -d "{\"goal\":\"find gold price India today\",\"provider\":\"gemini\"}"
```

Run an agent task through the gateway:

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"goal\":\"summarise top AI news today\",\"provider\":\"github\"}"
```

List tools:

```bash
curl http://localhost:8765/mcp-tools
```

Inspect graph:

```bash
curl http://localhost:8765/graph
```

Cancel a gateway session:

```bash
curl -X POST http://localhost:8000/api/sessions/<session_id>/cancel
```

## Stream Events

The backend streams JSON events:

| Event | Meaning |
|---|---|
| `status` | Progress message |
| `step` | Tool result snippet |
| `canvas` | Base64 browser screenshot |
| `done` | Final answer |
| `error` | Fatal error |
| `cancelled` | User cancelled the task |
| `system` | Session/provider notification |

## Tools

| Tool | Purpose |
|---|---|
| `search_web` | Search DuckDuckGo HTML results |
| `scrape` | Fetch static page text |
| `browse` | Navigate with Playwright Chromium |
| `click` | Click text or selector |
| `type_text` | Type into an input |
| `press_key` | Press keyboard keys |
| `wait` | Wait for page updates |
| `page_state` | Read current page state |
| `extract` | Extract data from the current browser page |

## Deployment

Recommended free/low-cost split:

| Part | Platform |
|---|---|
| React frontend in `web/` | Vercel |
| FastAPI backend, gateway, agent, Playwright | Render |

Notes:

- Vercel is best for the frontend.
- Render is better for the Python backend and browser automation.
- Render free services can sleep after idle time, so first request may be slow.
- Store secrets in platform environment variables.
- Use PostgreSQL instead of SQLite for production persistence.
- Keep backend to one process until session state is moved out of memory.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - full system architecture
- [docs/SETUP.md](docs/SETUP.md) - detailed setup
- [docs/TELEGRAM.md](docs/TELEGRAM.md) - Telegram setup
- [docs/EXTENSION.md](docs/EXTENSION.md) - Chrome extension setup
- [docs/PROVIDERS.md](docs/PROVIDERS.md) - provider details

## Safety Boundaries

AgenticWeb is designed to gather information and interact with pages, but it should not complete purchases, payments, bookings, account changes, or other irreversible actions. If a site requires login, premium access, or blocks automation, the agent should report that limitation and use public sources where possible.
