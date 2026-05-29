# Daily Work Log - 2026-05-29

## Summary

Today we improved AgenticWeb from a stateless web-agent demo into a more reliable session-aware agent. The main focus was:

- Fixing final answers getting stuck at `Working...`
- Adding usable context memory per user session
- Making summaries grounded in tool/site evidence instead of model guesses
- Making OpenRouter provider routing safer and more cost-aware
- Improving fallback behavior when free models are rate-limited

## Problems Found

### 1. Final Answer Was Missing Or Stuck

The UI sometimes showed `Working...` even after the backend had finished.

Root causes:

- The WebSocket could reconnect during a task.
- The frontend stored the active agent message in a volatile ref.
- If the final `done` event arrived after reconnect or after the ref was lost, the UI did not update the message bubble.

Fix:

- The web session ID is now stable in `localStorage`.
- `done`, `error`, and `cancelled` events update the latest running agent bubble even if the active message ref was lost.
- Disconnect handling now clears stuck running state.

Files:

- `web/src/App.jsx`
- `web/src/hooks/useAgentSocket.js`

### 2. Agent Did Not Remember Previous User Context

The project already had `memory.py`, but it only stored sessions and tool steps. The agent did not read that memory back into its prompt, so it answered:

> I don't have access to previous sessions or conversation history.

Fix:

- Added persistent `memory_items` table.
- Store goals, final answers, and task summaries.
- Retrieve relevant memory for the same session before each task.
- Added deterministic handling for explicit memory commands.

Example:

```text
Remember for this session: my preferred flight comparison site is MakeMyTrip.
```

Then:

```text
What is my preferred flight comparison site? Answer from memory only.
```

Returns:

```text
Your preferred flight comparison site is MakeMyTrip.
```

Files:

- `agent/skills/agenticweb/memory.py`
- `agent/skills/agenticweb/agent_loop.py`

### 3. Bad Memory Could Pollute Future Recall

During testing, a bad answer like "I don't have access to your memory" was stored and later retrieved as memory.

Fix:

- Filter bad memory entries before storing task summaries.
- Filter bad memory entries during recall.
- Structured facts are stored separately in the `facts` table.

### 4. Summary Ignored Useful Site Evidence

For flight comparison, the agent gathered useful evidence:

- Search result: MakeMyTrip fares from Bengaluru to Goa
- Scrape result: MakeMyTrip route page
- Scrape result: Skyscanner route page

Then it called `extract`, but `extract` reads the current live browser page. Because the browser page was blank or unrelated, it returned:

```json
{"raw": ""}
```

The final summary focused on that empty result and incorrectly said no sources were checked.

Fix:

- Final summarization now receives a full evidence block from all tool outputs.
- Empty tool outputs like `{"raw": ""}` are ignored.
- If the model says sources were `None` while evidence exists, the backend replaces it with a deterministic evidence summary.
- Prompt now says to use `extract` only after `browse` or `page_state`, not after `scrape`.

Files:

- `agent/skills/agenticweb/agent_loop.py`

## Context Memory Architecture

Current implementation is a local layered memory system using SQLite.

### Short-Term Memory

Scope:

- Current LangGraph state
- Recent messages
- Recent tool calls

Purpose:

- Lets the agent decide the next tool call during one task.

Implementation:

- LangGraph state in `agent_loop.py`
- Recent messages are trimmed to avoid context bloat

### Long-Term Session Memory

Scope:

- Same user/browser session
- Stored goals
- Final answers
- Task summaries
- Explicit user facts/preferences

Purpose:

- Lets the agent remember prior user preferences and previous work.

Implementation:

- SQLite database at `agent/data/memory.db`
- Tables:
  - `sessions`
  - `steps`
  - `facts`
  - `memory_items`

### Working Memory

Scope:

- Retrieved memory relevant to the current goal

Purpose:

- Prevents loading all past history into the prompt.
- Only a compact relevant memory block is injected.

Implementation:

- `recall_memory_context(session_id, goal)`
- Simple token-overlap scoring plus recency
- Injected into the main system prompt

Important detail:

- Memory is folded into the first `SystemMessage`.
- This avoids LangChain/Gemini errors caused by multiple system messages.

## Evidence-Grounded Summary Design

Final answers now follow this rule:

> If tools were used, answer only from tool evidence.

The agent should not invent:

- Prices
- Dates
- Flight availability
- Rankings
- Source names

Search-result snippets must be treated as leads, not verified live prices.

Expected format:

```text
Result
...

Sources Checked
...

Limitations
...
```

This is important for product trust. A web agent must clearly separate:

- What the website actually showed
- What came from search snippets
- What still needs live confirmation

## OpenRouter And Provider Routing

We added `openrouter_auto`, but kept it opt-in because it is not free.

Important distinction:

- `openrouter/auto` has no extra routing fee.
- It can still choose paid models.
- The app must not silently fall from free models into paid models.

Fix:

- Added cost-aware fallback chain.
- Paid fallback is disabled unless:
  - user explicitly selects a paid provider, or
  - `ALLOW_PAID_FALLBACKS=true`

Files:

- `agent/skills/agenticweb/llm_router.py`
- `.env.example`
- `docs/PROVIDERS.md`

## Current Test Checklist

### Memory

```text
Remember for this session: my preferred flight comparison site is MakeMyTrip.
```

Then:

```text
What is my preferred flight comparison site? Answer from memory only.
```

Expected:

```text
Your preferred flight comparison site is MakeMyTrip.
```

### Evidence Summary

```text
Compare Bengaluru to Goa flight prices for this Friday using search results from at least two travel sites. Do not book anything. Give cheapest options, source URLs, and clearly separate search-result snippets from verified live prices.
```

Expected:

- Should not say sources checked are `None`
- Should mention MakeMyTrip if search/scrape found it
- Should mention Skyscanner if scrape/search found it
- Should say search snippets are not verified live prices

### UI Stability

Start a task, then refresh/reconnect during execution.

Expected:

- UI should not stay stuck forever at `Working...`
- Backend sessions should show `running: false` after completion

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/sessions | ConvertTo-Json -Depth 5
```

## Known Limitations

- Memory retrieval is currently keyword/recency based, not vector search.
- Memory is per session ID, not yet per authenticated user.
- Flight websites often show dynamic prices; scraping may get route/page text but not real-time date-specific prices.
- OpenRouter free models can be rate-limited or inconsistent.
- Browser `extract` depends on the current live page, not prior scraped pages.

## Next Improvements

- Add a `source_evidence` structured object instead of plain text snippets.
- Add vector embeddings for better long-term memory retrieval.
- Add user identity so memory can persist across browsers/devices.
- Add a final-answer validator that rejects unsupported claims before sending to UI.
- Add provider health scoring and faster fallback timeout for summary-only calls.
- Add a memory/debug panel in the UI so users can see what the agent remembers.

