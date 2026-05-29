# Context Memory Architecture

## Purpose

AgenticWeb now uses a layered context-management design so agents can keep useful session state without stuffing every raw message and page dump into the LLM prompt.

The goal is to improve:

- continuity across tasks in the same session
- evidence-grounded final answers
- resistance to context bloat
- debuggability of what the agent tried, found, and still needs

## Current Design

The implementation is intentionally conservative. It adds a context layer beside the existing LangGraph message flow instead of replacing it. This keeps `ToolNode` and LangChain tool-calling stable.

Main files:

- `agent/skills/agenticweb/context_manager.py`
- `agent/skills/agenticweb/memory.py`
- `agent/skills/agenticweb/agent_loop.py`
- `gateway/main.py`
- `agent/server.py`

## Layers

### 1. Short-Term Execution State

Owned by LangGraph in `agent_loop.py`.

Contains:

- current task messages
- tool calls
- tool observations
- iteration count
- streaming status queue

Why we keep it:

- LangChain `ToolNode` expects message history containing tool calls and `ToolMessage` objects.
- Removing `messages` from `AgentState` would break the current tool execution path.

### 2. Structured Session Context

Owned by `ContextManager`.

Each session has a `SessionContext` with:

- immutable original goal
- active provider
- structured notes
- references
- compact message history
- optional compacted summary
- step counters and timestamps

Notes schema:

```text
goal
tried
found
pending
best_so_far
```

Rules:

- `goal` is never overwritten.
- `found` stores specific facts only, such as URLs, prices, route names, and source text.
- empty tool results are not treated as evidence.

### 3. Persistent Memory

Stored in SQLite at:

```text
agent/data/memory.db
```

Tables used:

- `sessions`
- `steps`
- `facts`
- `memory_items`
- `context_notes`
- `context_refs`

`context_notes` stores structured notes as JSON.

`context_refs` stores lightweight references:

```text
type
value
label
used
```

This allows the context manager to survive process restart for notes and references.

### 4. Context Block

Before each ACT step, the context manager builds a memory block and injects it into the first system message.

Format:

```text
=== SESSION MEMORY ===
Goal: ...

Notes:
  Tried: ...
  Found: ...
  Pending: ...
  Best so far: ...

References (unused):
  - [url] label: value

Steps completed: ...
=== END MEMORY ===
```

Important:

- The context block is inside the first system message.
- It is not sent as a separate `SystemMessage`, because some providers reject multiple system messages.

## Evidence-Grounded Summaries

Final summaries use:

- structured notes from `ContextManager`
- all tool evidence gathered across the run
- deterministic fallback if the model ignores evidence

The summary prompt requires:

- no invented prices
- no invented dates
- no invented availability
- source URLs beside claims where possible
- search snippets clearly marked as not verified live prices

Expected final-answer sections:

```text
Result
Sources Checked
Limitations
```

## Reference Handling

Search results are parsed into references when possible.

When `browse` or `scrape` returns a URL, matching references are marked as used.

Current behavior:

- references help the agent see unused sources in the context block
- references are not yet a hard cache

Reason:

- hard "never re-fetch" behavior is risky for date-sensitive or failed pages
- future work can add stale/fresh checks

## Compaction

The context manager can compact when:

- message history has more than 20 messages
- estimated history exceeds 12,000 tokens

Current compaction is deterministic and note-based:

- preserves original goal
- preserves found facts
- preserves pending items
- truncates compact history to the last 5 messages

Future versions can use an LLM compactor once provider reliability is stronger.

## Debugging

Gateway endpoint:

```text
GET http://127.0.0.1:8000/debug/context/<session_id>
```

Standalone agent endpoint:

```text
GET http://127.0.0.1:8765/debug/context/<session_id>
```

Use the gateway endpoint for Web UI sessions because the gateway runs the agent in-process.

## Manual Tests

### Memory Fact

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

### Context Debug

Run a web task, then call:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/debug/context/<session_id> | ConvertTo-Json -Depth 8
```

Expected:

- `notes.tried` has attempted steps
- `notes.found` has specific facts or URLs
- `references` contains search result URLs
- `message_history_count` is small

### Evidence Summary

```text
Compare Bengaluru to Goa flight prices for this Friday using search results from at least two travel sites. Do not book anything. Give cheapest options, source URLs, and clearly separate search-result snippets from verified live prices.
```

Expected:

- should not say sources checked are none if search/scrape found sources
- should list MakeMyTrip or Skyscanner if found
- should explain that snippets are not verified live booking prices

## Known Limitations

- The note updater is rule-based, not a full LLM note-taker yet.
- Reference caching is advisory, not strict.
- Context is keyed by session ID, not authenticated user ID.
- Vector memory is not implemented yet.
- Full raw page content is deliberately not retained in context history.

## Future Work

- Add vector retrieval over `memory_items`.
- Add source evidence objects with URL, claim, timestamp, confidence.
- Add a UI memory/debug panel.
- Add stale-reference policy for re-fetching dynamic data.
- Add LLM-assisted note updates behind a provider/cost guard.

