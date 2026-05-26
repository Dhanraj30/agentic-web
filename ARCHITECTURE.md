# AgenticWeb — Architecture

## Overview

AgenticWeb is a fully independent agentic web platform. No OpenClaw. No third-party gateway. Every component is purpose-built.

## Component map

### `gateway/main.py` — Control plane
FastAPI app on :8000. Owns:
- WebSocket server for React Web UI (`/ws/{session_id}`)
- REST endpoint for extension (`POST /api/chat` SSE)
- Telegram webhook handler (`POST /telegram/webhook`)
- Session registry (in-memory, one `Session` object per user)
- Routes messages from any channel → agent → back to channel

### `agent/server.py` — Agent API
Separate FastAPI app on :8765. Exposes:
- `POST /run` — SSE stream of agent events
- `GET /health` — stack info + available providers
- `GET /mcp-tools` — list of MCP tool schemas
- `GET /graph` — LangGraph topology
- `GET /providers` — full provider list with free/paid status

### `agent/skills/agenticweb/agent_loop.py` — LangGraph graph
Three nodes:
- `act` — LLM picks next MCP tool call using `bind_tools()`
- `observe` — ToolNode executes MCP tool, streams result + captures screenshot
- `summarise` — compiles final answer from conversation

Edges:
- `act → observe` if LLM made tool_calls
- `act → summarise` if no tool_calls or max iterations reached
- `observe → act` always (ReAct loop)

Optimizations:
- Sliding context window (last 6 messages)
- Tool results truncated to 2000 chars
- Early summarise when LLM answers without tools
- Max 5 iterations default

### `agent/skills/agenticweb/llm_router.py` — Multi-Provider LLM Router
Unified routing for all LLM providers:
- **Gemini** (`gemini`) — Google AI Studio, model from `GEMINI_MODEL` env var
- **Groq** (`groq`) — `llama-3.3-70b-versatile` via Groq API
- **DeepSeek** (`deepseek`) — `deepseek-chat` (V4 Flash) via DeepSeek API
- **Claude** (`claude`) — `claude-sonnet-4-6` via Anthropic API
- **OpenAI** (`openai`) — `gpt-4o-mini` via OpenAI API
- **OpenRouter** (`openrouter_*`) — 12 variants with different free models

Features:
- **Multi-key rotation**: `GEMINI_API_KEY`, `GEMINI_API_KEY_1`...`GEMINI_API_KEY_9` auto-detected
- **Cooldown integration**: skips rate-limited/billing-failed providers
- **Error classification**: rate_limit / billing / server_error / timeout / unknown

### `agent/skills/agenticweb/cooldown.py` — Cooldown Manager
Tracks per-provider failure state with exponential backoff (inspired by OpenClaw):
- Backoff: 60s → 300s → 1500s → 3600s (cap)
- Billing failure: 5h → 10h → 24h cap
- Persisted to `agent/data/cooldown_state.json`
- Auto-prunes expired entries every 5 minutes
- Failure counter resets after 24h of no failures

### `agent/skills/agenticweb/browser.py` — Playwright Browser
Manages a persistent Playwright Chromium browser instance:
- `navigate(url)` — Go to URL, wait for network idle
- `click(target)` — Click by text, label, role, or CSS selector
- `type_text(selector, text)` — Type into input fields
- `press_key(key)` — Keyboard key press
- `wait(seconds)` — Wait and return page state
- `page_state()` — Return title, URL, visible text
- `extract(instruction)` — AI-powered data extraction
- `take_screenshot()` — Capture JPEG screenshot (quality 40), base64 encoded
- `close_browser()` — Cleanup

### `agent/skills/agenticweb/mcp_tools/server.py` — MCP Server
Uses official `mcp` Python SDK (v1.1). Exposes 9 tools over stdio transport.

### `agent/skills/agenticweb/mcp_tools/client.py` — MCP→LangChain adapter
Wraps each MCP tool as `langchain_core.tools.BaseTool` for LangGraph.

### `agent/skills/agenticweb/memory.py` — SQLite Session Memory
Persists session state, goals, and step logs to SQLite.

### `agent/skills/agenticweb/scraper.py` — HTTP Scraper + Search
Fast HTTP fetcher for static pages + DuckDuckGo search integration.

### `web/` — React UI
Vite + React + Tailwind. Connects to gateway via WebSocket (`/ws/{sessionId}`).
Features:
- Real-time agent event streaming (status, step logs, errors)
- Live Canvas panel showing browser screenshots
- Provider switcher with free/paid indicators
- Suggestion chips for quick goals
- Stop/cancel running tasks

### `extension/` — Chrome MV3
Background service worker calls agent server directly (SSE).
Sidebar panel with live agent log.
Content script reads current page DOM for context.

---

## Data flow — Web UI message with Canvas

```
1. User types goal in React UI
2. React → WebSocket send {type:"chat", content:"...", provider:"gemini"}
3. Gateway session receives message
4. Gateway calls run_agent() → LangGraph starts
5. LangGraph ACT node: LLM picks tool (e.g. browse)
6. LangGraph OBSERVE: MCP client dispatches browser.navigate()
7. After tool execution, take_screenshot() captures page JPEG
8. Events streamed → asyncio.Queue → Gateway WebSocket:
   - {type:"step", tool:"browse", result:"..."}
   - {type:"canvas", data:"base64..."}
9. React renders step log + shows live screenshot in Canvas panel
10. LangGraph loops ACT→OBSERVE until no more tool calls
11. SUMMARISE node: LLM writes final answer
12. Gateway sends {type:"done", result:"..."} → React renders answer
```

---

## Data flow — Fallback + Cooldown

```
1. Primary provider (e.g. gemini) called via build_langchain_llm()
2. If rate-limit / timeout / billing error:
   a. Error classified (rate_limit / billing / server_error / timeout)
   b. CooldownManager.record_failure(provider, error_type)
   c. Exponential backoff written to cooldown_state.json
   d. Next provider in FALLBACK_ORDER tried
3. If success: CooldownManager.record_success(provider) clears state
4. provider_fallback_chain() filters out cooldown providers
5. If all providers on cooldown, tries first 3 anyway as fallback
```

---

## Provider system

### 16 providers across 5 backends

| Provider ID | Model | Key Env Var | Cost |
|---|---|---|---|
| `gemini` | `GEMINI_MODEL` (gemini-2.5-flash) | `GEMINI_API_KEY` | Free |
| `groq` | `llama-3.3-70b-versatile` | `GROQ_API_KEY` | Free |
| `deepseek` | `deepseek-chat` (V4 Flash) | `DEEPSEEK_API_KEY` | Cheap |
| `claude` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | Paid |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` | Paid |
| `openrouter_qwen` | `qwen/qwen3-next-80b-a3b-instruct:free` | `OPENROUTER_API_KEY` | Free |
| `openrouter_deepseek` | `deepseek/deepseek-v4-flash:free` | `OPENROUTER_API_KEY` | Free |
| `openrouter_fast` | `nvidia/nemotron-nano-9b-v2:free` | `OPENROUTER_API_KEY` | Free |
| `openrouter_free` | `openrouter/free` | `OPENROUTER_API_KEY` | Free |
| +8 more OpenRouter variants | Various free models | `OPENROUTER_API_KEY` | Free |

### Multi-key rotation
Each provider scans for env vars: `KEY`, `KEY_1`...`KEY_9`. Add multiple keys for automatic rotation on rate limits.

---

## MCP Tools (9 total)

| Tool | Description | Browser required |
|---|---|---|
| `browse` | Navigate to URL with real browser (JS rendered) | Yes |
| `click` | Click element by text or CSS selector | Yes |
| `type_text` | Type text into input field | Yes |
| `press_key` | Press keyboard key | Yes |
| `wait` | Wait and return page state | Yes |
| `page_state` | Read current page title, URL, visible text | Yes |
| `extract` | AI-powered structured data extraction | Yes |
| `scrape` | Fast HTTP fetch for static pages | No |
| `search_web` | DuckDuckGo search, top 5 results | No |

---

## Canvas — Live Browser Screenshots

**Feature**: After every browser tool call (browse, click, type_text, etc.), a JPEG screenshot is captured and streamed to the frontend as a `canvas` event.

**Implementation**:
- `browser.py`: `take_screenshot()` — captures JPEG at quality 40, returns base64
- `agent_loop.py`: In `observe_node`, after browser tool dispatch, calls `take_screenshot()` and emits `{"type": "canvas", "data": b64}`
- `App.jsx`: Receives canvas event, stores in state, shows in collapsible sidebar panel
- Toggle button in header: opens/closes the Canvas panel

**Performance**: JPEG quality 40 (~50KB per screenshot), only captured after browser-specific tools.

---

## Optimization Summary

| Optimization | Before | After | Improvement |
|---|---|---|---|
| System prompt | ~250 words | ~80 words | 68% fewer prompt tokens |
| Max iterations | 8 | 5 | 37.5% fewer LLM calls |
| Context window | Full history | Last 6 msg sliding | Bounded context growth |
| Tool results in state | Full content | 2000 char truncation | ~70% smaller state |
| Summarize context | Full history | Goal + last 3 msgs | Smaller final call |
| Early summarise | Always ACT→OBSERVE→SUMMARISE | Skip OBSERVE if no tools | 33% fewer steps |
| Provider failover | Static order | Cooldown-aware rotation | Faster recovery |
| Multi-key support | Single key per provider | KEY, KEY_1...KEY_9 | Better uptime |

---

## Scaling notes

| Concern | Now | Scale-up path |
|---|---|---|
| Sessions | In-memory dict | Redis |
| Memory | SQLite | PostgreSQL |
| Agent workers | Single process | uvicorn --workers 4 |
| Browser | Local Playwright | Browserless.io remote CDP |
| Web UI | Vite dev server | Build + serve static (nginx) |
| Telegram | Webhook | Works as-is at scale |

---

## Adding a new tool

1. Implement `async def my_tool(args) -> str` in `browser.py` or `scraper.py`
2. Add `Tool(name="my_tool", ...)` in `mcp_tools/server.py` `list_tools()`
3. Add dispatch in `mcp_tools/server.py` `call_tool()`
4. Add `MCPTool(name="my_tool", ...)` in `mcp_tools/client.py` `get_mcp_tools()`
5. (Optional) Add tool to `browser_tools` set in `agent_loop.py` for Canvas screenshots

## Adding a new channel

1. Add handler in `gateway/main.py`
2. Create/get `Session` with `channel="yourname"`
3. Implement `session.send()` for your channel's message format
4. Call `_run_agent_task(session, goal)`

## Adding a new LLM provider

1. Add env var to `KEY_MAP` in `llm_router.py`
2. Add position in `FALLBACK_ORDER` list
3. Add `elif` branches in `_call()` and `build_langchain_llm()`
4. Add provider entry in `gateway/main.py` and `agent/server.py` provider lists
5. Add to dropdown in `web/src/App.jsx` and extension HTML files
