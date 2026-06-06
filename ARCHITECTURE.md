# AgenticWeb - System Architecture

## 1. Purpose

AgenticWeb is an autonomous web-agent platform built around a LangGraph ReAct loop, MCP-style tools, a real Playwright browser, HTTP scraping, provider fallback, and multi-channel delivery.

The system is designed to accept a user goal from the web UI, Chrome extension, REST/SSE client, or Telegram; execute web-search and browser actions; stream progress and screenshots; persist session memory; and return a grounded final answer.

AgenticWeb is purpose-built. It does not depend on OpenClaw or a third-party agent gateway.

## 2. High-Level Architecture

```text
User Channels
  - React Web UI
  - Chrome Extension
  - Telegram Bot
  - REST/SSE clients
        |
        v
Gateway API - gateway/main.py
  - WebSocket endpoint
  - REST/SSE endpoint
  - Telegram webhook
  - In-memory session registry
  - Provider selection and cancellation
        |
        v
Agent Runtime - agent/skills/agenticweb/agent_loop.py
  - LangGraph state machine
  - Context manager
  - SQLite memory
  - Provider fallback
  - Event streaming
        |
        v
Tool Layer
  - LangChain tool adapter
  - MCP stdio server
  - Browser tools
  - Search and scraper tools
        |
        v
External Systems
  - LLM providers
  - Playwright Chromium
  - DuckDuckGo HTML search
  - Target websites
  - SQLite database
```

## 3. Runtime Components

### 3.1 Gateway Control Plane

File: `gateway/main.py`

The gateway is the main user-facing control plane. It owns connection management, channel routing, provider selection, and cancellation.

Main responsibilities:

- Accept web UI connections over `WebSocket /ws/{session_id}`.
- Accept extension and external calls over `POST /api/chat`.
- Stream REST responses as Server-Sent Events.
- Accept Telegram messages through `POST /telegram/webhook`.
- Maintain an in-memory `SessionRegistry`.
- Track one active `Session` per user/channel.
- Route events emitted by `run_agent()` back to the correct channel.
- Cancel active agent tasks when the user sends stop/cancel.
- Close the Playwright browser on shutdown.

Important endpoints:

| Endpoint | Purpose |
|---|---|
| `WS /ws/{session_id}` | Web UI bidirectional event stream |
| `POST /api/chat` | REST/SSE agent run for extension and external callers |
| `GET /api/health` | Gateway health, channels, providers, active sessions |
| `GET /api/sessions` | Active in-memory sessions |
| `POST /api/sessions/{session_id}/cancel` | Cancel a running task |
| `GET /api/providers` | Provider list for UI/client selection |
| `GET /debug/context/{session_id}` | Inspect live context manager state |
| `POST /telegram/webhook` | Telegram update receiver |

Session behavior:

- A `Session` stores `session_id`, channel, WebSocket, Telegram chat id, selected provider, running flag, and active asyncio task.
- Web sessions receive JSON events directly over WebSocket.
- Telegram sessions receive formatted text messages through the Telegram Bot API.
- Extension sessions receive events through SSE.
- The registry is in-memory, so active connection state is not shared across processes.

### 3.2 Agent API Server

File: `agent/server.py`

The agent server exposes the same agent runtime as a direct API on the agent process. It is useful for local development, direct extension access, debugging, and service separation.

Important endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /run` | Run an agent task and stream events as SSE |
| `GET /health` | Agent health and available providers |
| `GET /providers` | Provider list |
| `GET /graph` | Static LangGraph topology |
| `GET /mcp-tools` | LangChain/MCP tool names and descriptions |
| `GET /debug/context/{session_id}` | Inspect context state in this process |

The gateway currently imports and calls `run_agent()` directly, while the agent server also exposes it as an independent HTTP/SSE service.

### 3.3 LangGraph Agent Loop

File: `agent/skills/agenticweb/agent_loop.py`

The agent loop is a compiled LangGraph state machine with three nodes:

```text
act -> observe -> act -> ... -> summarise -> END
```

State fields:

| Field | Meaning |
|---|---|
| `messages` | LangChain message history used by LangGraph |
| `goal` | User task |
| `session_id` | Runtime and persistence key |
| `iteration` | Number of ACT turns |
| `step_count` | Number of OBSERVE/tool steps |
| `status_queue` | Async queue used to stream events to caller |
| `final_answer` | Final answer, when complete |
| `memory_context` | Relevant memory block loaded before the run |

Node responsibilities:

| Node | Responsibility |
|---|---|
| `act` | Build the prompt, attach compact context/memory, bind tools, call the selected LLM with fallback |
| `observe` | Execute tool calls through `ToolNode`, stream step events, log steps, update context notes, capture screenshots |
| `summarise` | Produce final answer using gathered evidence and structured notes |

Graph routing:

- `act -> observe` when the model emitted tool calls and max iterations has not been reached.
- `act -> summarise` when there are no tool calls, tool evidence is already enough, or max iterations is reached.
- `observe -> act` after every tool execution.
- `summarise -> END` after emitting the final `done` event.

Runtime limits and optimizations:

- `AGENT_MAX_ITERATIONS` controls the max loop count; default is `5`.
- ACT uses a sliding message window when the message list grows.
- Tool results are truncated before being stored back into graph state.
- Tool evidence is preserved separately for final summarization.
- The summary prompt uses structured notes plus recent messages rather than the full raw transcript.
- If the model gives a useful direct answer without tools, the loop can finalize early.
- If a provider fails after tools have gathered evidence, the system can produce a fallback summary instead of losing the run.

### 3.4 Context Manager

File: `agent/skills/agenticweb/context_manager.py`

The context manager keeps a compact structured view of progress for each active session. It complements LangGraph messages instead of replacing them.

Tracked context:

- Goal.
- Provider.
- Structured notes:
  - `goal`
  - `tried`
  - `found`
  - `pending`
  - `best_so_far`
- References discovered from search results.
- Whether references have been used.
- Recent message history.
- Compacted summary.
- Step count.

Persistence:

- Notes are saved through `save_context_notes()`.
- References are saved through `save_context_reference()`.
- Data is stored in SQLite tables managed by `memory.py`.

Compaction:

- `should_compact()` triggers when message history is too large.
- `compact()` summarizes recent attempts, findings, pending work, and best candidates.
- `build_messages_for_llm()` injects the context block into the system prompt for later ACT calls.

Reference tracking:

- `search_web` results are parsed into URL references.
- `browse` and `scrape` mark URLs as used when those URLs appear in tool output.
- Unused references are shown back to the LLM as pending sources.

### 3.5 SQLite Memory Layer

File: `agent/skills/agenticweb/memory.py`

SQLite stores sessions, steps, facts, task summaries, context notes, and references.

Database path:

```text
agent/data/memory.db
```

Tables:

| Table | Purpose |
|---|---|
| `sessions` | Session id, goal, provider, creation time, status |
| `steps` | Tool execution log by step number |
| `facts` | Remembered user facts/preferences for a session |
| `memory_items` | Goals, final answers, and task summaries |
| `context_notes` | JSON-encoded structured context notes |
| `context_refs` | URL/reference tracking and used flag |

Memory features:

- `create_session()` creates or replaces the active session and stores the goal.
- `log_step()` records each tool result.
- `complete_session()` marks a run complete and stores the final answer.
- `record_task_summary()` persists a grounded summary with recent evidence.
- `recall_memory_context()` retrieves relevant prior memory from the same session.
- `handle_memory_request()` answers simple "remember" and memory-question commands without running the full agent.

Memory is session-scoped in the current implementation. It is not yet a global user profile or cross-user long-term memory system.

## 4. Tool Architecture

### 4.1 Tool Boundary

AgenticWeb has two compatible tool interfaces:

1. In-process LangChain tools used by LangGraph.
2. A standalone MCP stdio server for protocol compatibility.

The active LangGraph path uses the in-process adapter in `mcp_tools/client.py` to avoid subprocess overhead. The MCP server in `mcp_tools/server.py` exposes the same tool set over stdio for external MCP clients.

### 4.2 LangChain Tool Adapter

File: `agent/skills/agenticweb/mcp_tools/client.py`

Responsibilities:

- Define Pydantic input schemas for each tool.
- Wrap each tool as `langchain_core.tools.BaseTool`.
- Dispatch tool calls to browser or scraper functions.
- Return strings suitable for LangGraph `ToolMessage` objects.

Tool execution path:

```text
LLM tool_call
  -> LangGraph ToolNode
  -> MCPTool._arun()
  -> _dispatch()
  -> browser.py or scraper.py
  -> ToolMessage
```

### 4.3 MCP Stdio Server

File: `agent/skills/agenticweb/mcp_tools/server.py`

Responsibilities:

- Register the `agenticweb-tools` MCP server.
- List tool schemas through `@mcp.list_tools()`.
- Execute calls through `@mcp.call_tool()`.
- Return MCP `CallToolResult` objects.
- Run over stdio through the official MCP Python SDK.

### 4.4 Tool List

| Tool | Implementation | Purpose | Browser required |
|---|---|---|---|
| `browse` | `browser.navigate()` | Navigate to a URL in Playwright Chromium | Yes |
| `click` | `browser.click()` | Click by visible text or selector | Yes |
| `type_text` | `browser.type_text()` | Type text into an input | Yes |
| `press_key` | `browser.press_key()` | Send a keyboard key | Yes |
| `wait` | `browser.wait()` | Wait and return current page state | Yes |
| `page_state` | `browser.page_state()` | Read title, URL, and visible text | Yes |
| `extract` | `browser.extract()` | Extract structured data from current live page | Yes |
| `scrape` | `scraper.scrape()` | Fetch and parse static HTML | No |
| `search_web` | `scraper.search_web()` | DuckDuckGo HTML search | No |

## 5. Browser and Canvas Architecture

File: `agent/skills/agenticweb/browser.py`

The browser layer manages a Playwright Chromium instance for JS-rendered pages and interactive tasks.

Browser tool calls can emit a live Canvas update:

```text
browser tool result
  -> observe_node detects browser tool
  -> take_screenshot()
  -> base64 JPEG
  -> {"type": "canvas", "data": "..."}
  -> web UI renders latest screenshot
```

Canvas events are only emitted for browser-backed tools:

- `browse`
- `click`
- `type_text`
- `press_key`
- `wait`
- `page_state`
- `extract`

Static tools such as `search_web` and `scrape` do not capture screenshots.

## 6. Search and Scraping

File: `agent/skills/agenticweb/scraper.py`

The scraper is optimized for fast static content retrieval without opening a browser.

`scrape(url, instruction="", llm_router=None)`:

- Uses `httpx.AsyncClient`.
- Follows redirects.
- Uses browser-like headers.
- Parses HTML with BeautifulSoup.
- Removes scripts, styles, nav, footer, iframe, and aside tags.
- Returns compact page text.
- Can optionally run an extraction prompt if an `llm_router` is supplied.

`search_web(query)`:

- Posts to DuckDuckGo HTML search.
- Parses top results.
- Extracts wrapped `uddg` target URLs.
- Returns title, URL, and snippet dictionaries.

Search output is formatted by the tool adapter so the context manager can parse references.

## 7. LLM Provider Architecture

File: `agent/skills/agenticweb/llm_router.py`

The LLM router normalizes provider selection and failover. The agent asks for a preferred provider, then `provider_fallback_chain()` returns an ordered list of usable candidates.

Supported provider families include:

- Gemini / Google AI Studio.
- Groq.
- DeepSeek.
- Claude / Anthropic.
- OpenAI.
- GitHub Models.
- Azure OpenAI.
- OpenRouter direct, auto, paid, and free-model variants.

Provider runtime behavior:

- ACT calls bind tools to the selected LLM.
- Some providers can be skipped for tool use if known to be unreliable for tool routing.
- Each LLM call is wrapped in an async timeout.
- Rate limits, quota failures, server failures, billing errors, and tool-routing errors are classified as fallback-worthy.
- Successful calls clear cooldown state.
- Failed calls record cooldown state.
- OpenRouter free daily quota exhaustion skips other OpenRouter free models for that run.

Provider events:

- Initial provider is selected by the user, session default, or `AGENT_PROVIDER`.
- Fallback attempts emit status events like `Trying fallback provider: ...`.
- If all providers fail before a final answer, the user receives a clear provider-unavailable message.

## 8. Cooldown and Resilience

File: `agent/skills/agenticweb/cooldown.py`

The cooldown manager prevents repeated calls to providers that are temporarily unusable.

Responsibilities:

- Track provider failures.
- Apply longer cooldowns for billing/credit failures.
- Apply shorter cooldowns for transient rate limits or server failures.
- Persist state to `agent/data/cooldown_state.json`.
- Let provider fallback skip providers under cooldown.
- Clear provider state after success.

Resilience behavior in the agent loop:

- If ACT fails before useful tool evidence exists, fallback providers are attempted.
- If a provider fails after evidence exists, the agent can produce a grounded fallback summary.
- If the summary model fails, `_fallback_summary()` reports gathered evidence and limitations instead of inventing missing facts.

## 9. Event Streaming Contract

AgenticWeb streams simple JSON events from `run_agent()` to whichever channel started the task.

Common event types:

| Event type | Meaning |
|---|---|
| `status` | Human-readable progress update |
| `step` | Tool execution result snippet |
| `canvas` | Base64 screenshot from live browser |
| `done` | Final answer |
| `error` | Fatal non-provider error |
| `cancelled` | Task was cancelled by the user |
| `system` | Provider/session-level notification |
| `pong` | WebSocket heartbeat response |

Example stream:

```json
{"type":"status","message":"Initialising agent..."}
{"type":"status","message":"Thinking... (step 1)"}
{"type":"status","message":"Searching: gold price India today"}
{"type":"step","step":1,"tool":"search_web","result":"[1] ..."}
{"type":"status","message":"Scraping https://example.com"}
{"type":"step","step":2,"tool":"scrape","result":"..."}
{"type":"done","result":"Result\n..."}
```

## 10. Primary Data Flows

### 10.1 Web UI With Canvas

```text
1. User submits a goal in the React UI.
2. UI sends {"type":"chat","content":"...","provider":"..."} over WebSocket.
3. gateway/main.py gets or creates the Session.
4. Gateway starts _run_agent_task().
5. run_agent() creates SQLite session and context-manager session.
6. Memory layer checks whether the request can be answered from remembered facts.
7. LangGraph ACT calls the selected provider with tools bound.
8. LLM emits tool calls.
9. OBSERVE executes tool calls through ToolNode and MCPTool adapter.
10. Tool results are streamed as step events.
11. Browser tools capture a screenshot and stream a canvas event.
12. Context notes, references, and SQLite step logs are updated.
13. ACT/OBSERVE repeats until the graph should summarize.
14. SUMMARISE writes a final answer from evidence and structured notes.
15. Gateway forwards the done event to the WebSocket.
```

### 10.2 Extension or REST/SSE Call

```text
1. Client posts goal/session/provider to POST /api/chat or POST /run.
2. FastAPI validates the request.
3. run_agent() is called.
4. Events are yielded as SSE data frames.
5. Client renders status, step, canvas, done, or error events.
```

### 10.3 Telegram Message

```text
1. Telegram sends an update to /telegram/webhook.
2. Gateway extracts chat id and text.
3. Commands are handled directly:
   - /start
   - /status
   - /stop or /cancel
   - /provider <id>
4. Normal text starts an agent task for that chat id.
5. Agent events are formatted for Telegram.
6. Telegram messages are truncated to Telegram's message size limit.
```

### 10.4 Provider Fallback

```text
1. User/session selects a preferred provider.
2. provider_fallback_chain() orders candidates.
3. ACT or SUMMARISE calls build_langchain_llm().
4. If tools are needed, bind_tools() is applied.
5. LLM call runs with timeout.
6. On success:
   - cooldown.record_success(provider)
   - result returns to graph
7. On fallback-worthy failure:
   - cooldown.record_failure(provider)
   - status event announces fallback provider
   - next provider is tried
8. If all providers fail:
   - use fallback summary if evidence exists
   - otherwise emit provider-unavailable final message
```

## 11. Persistence and State Boundaries

| State | Location | Lifetime |
|---|---|---|
| Active WebSocket/Telegram task | Gateway process memory | Until process restart or disconnect |
| LangGraph state | Agent task memory | One run |
| Context manager sessions | Agent process memory plus SQLite notes/refs | Active run, partially persisted |
| Step logs | SQLite `steps` table | Persistent |
| Goals and answers | SQLite `memory_items` table | Persistent |
| Remembered facts | SQLite `facts` table | Persistent |
| Cooldown state | JSON file | Persistent until expiry/success |
| Browser page/session | Playwright process memory | Until browser closes |

Important boundary:

- In-memory gateway sessions and context-manager objects are not shared across multiple worker processes.
- SQLite persistence survives restart, but active tasks do not.
- Browser state is local to the running process.

## 12. Frontend Architecture

Directory: `web/`

The web UI is a Vite + React + Tailwind application.

Responsibilities:

- Generate or reuse a session id.
- Connect to `gateway/main.py` through `/ws/{sessionId}`.
- Send chat messages, provider changes, stop requests, and pings.
- Render streamed status and step logs.
- Render final answers.
- Show live Canvas screenshots from `canvas` events.
- Expose provider selection with free/paid indicators.

The web UI is intentionally thin: agent execution, memory, browser automation, and provider fallback all live in the backend.

## 13. Chrome Extension Architecture

Directory: `extension/`

The Chrome MV3 extension is another client for the agent runtime.

Expected responsibilities:

- Collect current page context through content scripts.
- Send tasks to the backend through REST/SSE.
- Render live agent logs in the side panel or extension UI.
- Stream completion/error events from the server.

The extension can call the gateway `/api/chat` endpoint or the agent server `/run` endpoint depending on deployment topology.

## 14. Deployment Architecture

### Recommended Simple Deployment

For a free or low-cost deployment:

```text
Vercel
  - React frontend from web/

Render
  - FastAPI gateway/agent backend
  - Playwright browser dependencies
  - SQLite or external database
```

Recommended split:

- Deploy the React frontend to Vercel.
- Deploy the FastAPI backend to Render as a Web Service.
- Point the frontend WebSocket/API URL to the Render backend.
- Store all `.env` values in platform environment-variable settings.
- Do not commit `.env`.

Backend deployment considerations:

- Render free web services sleep when idle, so the first request after idle can be slow.
- Playwright requires browser binaries and system dependencies.
- SQLite works for demos and single-instance deployments.
- Use PostgreSQL for persistent production data.
- Use one backend process for in-memory session consistency, or move session state to Redis before scaling horizontally.

### Production Scale-Up Path

| Concern | Current design | Scale-up path |
|---|---|---|
| Gateway sessions | In-memory dict | Redis or database-backed session store |
| Active task queue | asyncio task per process | Queue workers with Redis/RQ/Celery/Arq |
| SQLite memory | Local file | PostgreSQL |
| Browser runtime | Local Playwright | Browserless, remote CDP, or browser worker pool |
| Provider cooldown | Local JSON file | Redis/shared cache |
| WebSocket scaling | Single process | Sticky sessions or shared pub/sub |
| Logs | Console + SQLite steps | Centralized logging/observability |
| Secrets | `.env` locally | Platform secret manager |

## 15. Configuration

Common environment variables:

| Variable | Purpose |
|---|---|
| `GATEWAY_PORT` | Gateway port, default `8000` |
| `AGENT_PORT` | Agent server port, default `8765` |
| `AGENT_PROVIDER` | Default provider, default `gemini` |
| `AGENT_MAX_ITERATIONS` | Max ACT iterations, default `5` |
| `LLM_CALL_TIMEOUT_SECONDS` | LLM call timeout, default `35` |
| `TELEGRAM_BOT_TOKEN` | Enables Telegram webhook handling |
| `GEMINI_API_KEY` | Gemini provider key |
| `GROQ_API_KEY` | Groq provider key |
| `DEEPSEEK_API_KEY` | DeepSeek provider key |
| `ANTHROPIC_API_KEY` | Claude provider key |
| `OPENAI_API_KEY` | OpenAI provider key |
| `OPENROUTER_API_KEY` | OpenRouter provider key |

Provider key rotation:

- Providers can scan numbered key variants such as `KEY_1` through `KEY_9` where supported by the router.
- Multiple keys improve free-tier uptime and reduce rate-limit stalls.

## 16. Safety and Policy Boundaries

The system prompt and tool policy enforce these boundaries:

- Search first when the exact URL is unknown.
- Use multiple sources for comparisons.
- Prefer static search/scrape for simple data gathering.
- Use browser interaction for JS-heavy or form-driven pages.
- Do not complete purchases, payments, bookings, or account changes.
- Stop retrying selectors/actions after repeated failures.
- Report login, premium-access, or blocked-site limitations.
- Do not fabricate prices, URLs, names, rankings, or source claims.
- Summaries must be grounded in tool evidence.

## 17. Adding or Changing Capabilities

### Add a New Tool

1. Implement the function in `browser.py`, `scraper.py`, or a new tool module.
2. Add the tool schema to `agent/skills/agenticweb/mcp_tools/server.py`.
3. Add dispatch logic to `mcp_tools/server.py`.
4. Add a Pydantic input schema and `MCPTool` entry in `mcp_tools/client.py`.
5. If the tool changes the live page, add it to the `browser_tools` set in `agent_loop.py` so Canvas screenshots are emitted.
6. Update this architecture file and any UI labels if the tool is user-visible.

### Add a New Channel

1. Add a handler in `gateway/main.py`.
2. Create or retrieve a `Session` with a new channel name.
3. Extend `Session.send()` to format events for that channel.
4. Start `_run_agent_task(session, goal)` for normal messages.
5. Add channel health/status information if needed.

### Add a New LLM Provider

1. Add environment-variable support in `llm_router.py`.
2. Add provider construction in `build_langchain_llm()`.
3. Add fallback ordering in `provider_fallback_chain()` or the provider list used by it.
4. Decide whether the provider supports tool calling reliably.
5. Add cooldown/error classification if the provider returns unique error shapes.
6. Add provider metadata to `gateway/main.py`, `agent/server.py`, and frontend provider selection.

## 18. Known Architectural Constraints

- Gateway session state is process-local.
- Context manager live state is process-local.
- SQLite is not suitable for multi-instance production writes without careful deployment constraints.
- Browser automation is resource-heavy on small free containers.
- Telegram webhook setup is logged for manual configuration.
- The agent server `/graph` endpoint is static and should be kept in sync with `AGENT_MAX_ITERATIONS`.
- Some OpenRouter free models may not reliably support tool calls, so the agent skips known-unreliable providers for tool-bound ACT calls.
- Search is based on DuckDuckGo HTML parsing, which can change or rate-limit.

## 19. Design Summary

AgenticWeb separates channel handling, agent reasoning, tool execution, and persistence:

- `gateway/main.py` handles users and channels.
- `agent_loop.py` handles reasoning and event streaming.
- `context_manager.py` keeps the run compact and source-aware.
- `memory.py` persists sessions, facts, steps, summaries, notes, and references.
- `mcp_tools/client.py` bridges LangGraph to tools.
- `mcp_tools/server.py` provides MCP compatibility.
- `browser.py` handles live web interaction and screenshots.
- `scraper.py` handles fast static fetching and search.
- `llm_router.py` and `cooldown.py` keep provider selection resilient.

The result is a modular autonomous web agent that can run locally, support multiple frontends, stream progress in real time, and scale toward production by externalizing session state, memory, cooldowns, and browser execution.
