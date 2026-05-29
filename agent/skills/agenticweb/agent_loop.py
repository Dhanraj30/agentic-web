"""
AgenticWeb — LangGraph Agent Loop
===================================
State machine: ACT → OBSERVE → SUMMARISE

  ACT      — LLM picks next MCP tool call
  OBSERVE  — execute MCP tool, stream result
  SUMMARISE— compile final answer

Streams events via asyncio.Queue to caller.
"""
from __future__ import annotations
import asyncio
import logging
import os
import uuid
from typing import Annotated, Any, AsyncGenerator, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .browser import take_screenshot as _take_screenshot
from .context_manager import ContextManager, parse_references_from_search_result
from .llm_router import OPENROUTER_FREE_PROVIDERS, build_langchain_llm, cooldown, provider_fallback_chain
from .memory import complete_session, create_session, handle_memory_request, log_step, recall_memory_context, record_task_summary
from .mcp_tools.client import get_mcp_tools

logger = logging.getLogger(__name__)
MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "5"))
TOOL_ROUTER_UNRELIABLE_PROVIDERS = {"openrouter_free"}
context_manager = ContextManager()

SYSTEM_PROMPT = """You are AgenticWeb — an autonomous web agent with MCP tools to browse, search, scrape, extract, and interact with web pages.

Rules:
- search_web first if you lack the exact URL
- For comparisons, gather evidence from at least two different sources before answering
- Prefer search_web and scrape for price/news/data comparisons; use live clicks/forms only when static sources cannot answer
- If a site blocks interaction or a selector fails, switch source or summarise what was gathered instead of retrying the same form
- browse for JS-heavy sites, scrape for static pages
- extract only after browse/page_state, because it reads the current live browser page; do not use extract on scrape output
- If the same selector/action fails twice, stop retrying that selector. Switch strategy or explain the blocker.
- If a site requires login or premium access, report that limitation and use public sources or local reasoning instead of looping.
- Do NOT complete purchases, payments, bookings, or account changes
- Never fabricate data — report real prices, URLs, names
- Be concise. Show progress. Move fast."""


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    goal: str
    session_id: str
    iteration: int
    step_count: int
    status_queue: Any
    final_answer: Optional[str]
    memory_context: str


async def act_node(state: AgentState, config: RunnableConfig) -> dict:
    q: asyncio.Queue = state["status_queue"]
    iteration = state["iteration"] + 1
    await q.put({"type": "status", "message": f"Thinking… (step {iteration})"})

    tools = get_mcp_tools()
    session_id = state["session_id"]
    if context_manager.should_compact(session_id):
        await q.put({"type": "status", "message": "Compacting context..."})
        await context_manager.compact(session_id)
    msgs = list(state["messages"])
    if len(msgs) > 6:
        msgs = [msgs[0]] + msgs[-5:]
    memory = state.get("memory_context", "")
    system_prompt = SYSTEM_PROMPT if not memory else f"{SYSTEM_PROMPT}\n\n{memory}"
    context_messages = context_manager.build_messages_for_llm(session_id, system_prompt)
    messages = [context_messages[0] if context_messages else SystemMessage(content=system_prompt)] + msgs
    try:
        response: AIMessage = await _invoke_with_provider_fallback(
            messages=messages,
            provider=config.get("configurable", {}).get("provider"),
            q=q,
            tools=tools,
        )
    except Exception as e:
        if _should_try_next_provider(e) and any(isinstance(m, ToolMessage) for m in state["messages"]):
            await q.put({"type": "status", "message": "LLM unavailable; using gathered results."})
            return {"messages": [AIMessage(content="")], "iteration": iteration}
        raise
    context_manager.append_message(session_id, response)
    return {"messages": [response], "iteration": iteration}


async def observe_node(state: AgentState) -> dict:
    q: asyncio.Queue = state["status_queue"]
    tools = get_mcp_tools()
    tool_node = ToolNode(tools)
    last_msg = state["messages"][-1]
    step = state["step_count"] + 1

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            name = tc.get("name", "tool")
            args = tc.get("args", {})
            await q.put({"type": "status", "message": _describe(name, args)})

    result = await tool_node.ainvoke({"messages": state["messages"]})
    new_messages = result.get("messages", [])
    ctx = context_manager.get(state["session_id"])
    if ctx:
        ctx.step_count = step

    browser_tools = {"browse", "click", "type_text", "press_key", "wait", "page_state", "extract"}
    for msg in new_messages:
        if isinstance(msg, ToolMessage):
            tool_name = msg.name or "tool"
            snippet = str(msg.content)[:300]
            await q.put({"type": "step", "step": step, "tool": tool_name, "result": snippet})
            await log_step(state["session_id"], step, tool_name, "call", {}, snippet, "done")
            await context_manager.update_notes(state["session_id"], str(msg.content), tool_name)
            if tool_name == "search_web":
                for ref in parse_references_from_search_result(str(msg.content)):
                    await context_manager.add_reference(state["session_id"], ref["type"], ref["value"], ref["label"])
            if tool_name in {"browse", "scrape"}:
                for url in _urls_from_text(str(msg.content)):
                    await context_manager.mark_reference_used(state["session_id"], url)
            context_manager.append_message(
                state["session_id"],
                ToolMessage(content=str(msg.content)[:500], tool_call_id=getattr(msg, "tool_call_id", "") or "tool", name=tool_name),
            )
            msg.content = str(msg.content)[:2000]
            if tool_name in browser_tools:
                b64 = await _take_screenshot()
                if b64:
                    await q.put({"type": "canvas", "data": b64})

    return {"messages": new_messages, "step_count": step}


async def summarise_node(state: AgentState, config: RunnableConfig) -> dict:
    q: asyncio.Queue = state["status_queue"]
    last = state["messages"][-1] if state["messages"] else None
    has_tool_evidence = any(isinstance(m, ToolMessage) for m in state["messages"])

    if not has_tool_evidence and last and isinstance(last, AIMessage) and not getattr(last, "tool_calls", None) and last.content and len(str(last.content)) > 30:
        answer = _clean_answer(_content_to_text(last.content))
        await _finalize_session(state, answer)
        await q.put({"type": "done", "result": answer})
        return {"final_answer": answer}

    await q.put({"type": "status", "message": "Compiling final answer…"})
    msgs = list(state["messages"])
    if len(msgs) > 4:
        msgs = [msgs[0]] + msgs[-3:]
    evidence = _tool_evidence(state)
    evidence_block = _format_evidence_block(evidence)
    ctx = context_manager.get(state["session_id"])
    structured_notes = _format_notes_for_summary(ctx.notes if ctx else {})
    msgs.append(HumanMessage(content=(
        f"Goal: {state['goal']}\n"
        f"Structured session notes:\n{structured_notes}\n\n"
        f"Tool evidence gathered across the whole run:\n{evidence_block}\n\n"
        "Write the final answer using only the tool evidence in this conversation.\n"
        "Rules:\n"
        "- Do not invent prices, dates, availability, rankings, source names, company tags, execution output, or hidden page data.\n"
        "- If a page requires login or premium access, say that directly and do not guess hidden data.\n"
        "- Mention live prices only when the user asked for prices or the evidence contains prices.\n"
        "- Include source URLs beside each claim when possible.\n"
        "- If comparison/data collection is incomplete, say exactly what was checked and what remains unverified.\n"
        "- Format cleanly with: Result, Sources Checked, Limitations."
    )))
    try:
        response = await _invoke_with_provider_fallback(
            messages=msgs,
            provider=config.get("configurable", {}).get("provider"),
            q=q,
        )
        answer = _clean_answer(_content_to_text(response.content if hasattr(response, "content") else response))
        if not answer.strip():
            answer = _fallback_summary(state, reason="The summary model returned an empty answer.")
        elif _answer_ignores_evidence(answer, evidence):
            answer = _fallback_summary(state, reason="The summary model ignored available tool evidence.")
    except Exception as e:
        if not _should_try_next_provider(e):
            raise
        answer = _fallback_summary(state, reason="The selected LLM provider was unavailable while writing the final summary.")

    await _finalize_session(state, answer, evidence)
    await q.put({"type": "done", "result": answer})
    return {"final_answer": answer}


def should_continue(state: AgentState) -> str:
    if state["iteration"] >= MAX_ITERATIONS:
        return "summarise"
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "observe"
    has_tools = any(isinstance(m, ToolMessage) for m in state["messages"])
    if has_tools and last and isinstance(last, AIMessage) and last.content and len(str(last.content)) > 30:
        return "summarise"
    if has_tools:
        return "summarise"
    return "summarise"


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    text = str(exc).lower()
    return "timeout" in text or "timed out" in text or "readtimeout" in text


def _is_provider_unavailable(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "500" in text
        or "402" in text
        or "payment required" in text
        or "requires more credits" in text
        or "internal server error" in text
        or "internal error encountered" in text
        or "statuscode.internal" in text
        or "no endpoints found" in text
        or "support tool use" in text
        or "temporarily rate-limited upstream" in text
        or "provider returned error" in text
        or "tool_use_failed" in text
        or "failed_generation" in text
        or "failed to call a function" in text
        or "<function=" in text
        or "does not support image input" in text
        or "cannot read" in text and "clipboard" in text
    )


def _should_try_next_provider(exc: Exception) -> bool:
    return _is_rate_limit(exc) or _is_timeout(exc) or _is_provider_unavailable(exc)


def _is_openrouter_free_daily_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "free-models-per-day" in text or "x-ratelimit-remaining': '0" in text or '"x-ratelimit-remaining": "0' in text


async def _invoke_with_provider_fallback(
    messages: list[BaseMessage],
    provider: Optional[str],
    q: asyncio.Queue,
    tools: Optional[list] = None,
):
    last_error: Exception | None = None
    openrouter_free_exhausted = False
    for index, candidate in enumerate(provider_fallback_chain(provider)):
        if openrouter_free_exhausted and candidate in OPENROUTER_FREE_PROVIDERS:
            continue
        if tools and candidate in TOOL_ROUTER_UNRELIABLE_PROVIDERS:
            logger.info("Skipping provider %s for tool use; using tool-capable fallback.", candidate)
            continue
        if index:
            await q.put({"type": "status", "message": f"Trying fallback provider: {candidate}"})
        try:
            llm = build_langchain_llm(candidate)
            if tools:
                llm = llm.bind_tools(tools)
            result = await asyncio.wait_for(llm.ainvoke(messages), timeout=float(os.getenv("LLM_CALL_TIMEOUT_SECONDS", "35")))
            served_model = getattr(result, "response_metadata", {}).get("model_name")
            if served_model:
                logger.info("Provider %s served by model %s", candidate, served_model)
            cooldown.record_success(candidate)
            return result
        except Exception as e:
            last_error = e
            if _is_openrouter_free_daily_limit(e):
                openrouter_free_exhausted = True
                await q.put({"type": "status", "message": "OpenRouter free daily quota exhausted; skipping other free OpenRouter models."})
            if _should_try_next_provider(e):
                cooldown.record_failure(candidate)
                logger.warning("Provider %s failed, trying fallback: %s", candidate, e)
                continue
            cooldown.record_failure(candidate, "billing" if "402" in str(e) or "payment" in str(e).lower() else "unknown")
            raise
    if last_error:
        raise last_error
    raise RuntimeError("No configured LLM provider is available.")


def _fallback_summary(state: AgentState, reason: str = "The agent could not complete the final LLM summary.") -> str:
    observations = _tool_evidence(state)
    if not observations:
        return (
            f"{reason} No reliable web results were gathered before the task stopped. "
            "Please retry with a more specific source, switch provider, or add another provider key."
        )

    lines = [
        "Result",
        f"{reason} I can only report the evidence gathered from tools; I will not invent missing details.",
        "",
        "Sources Checked",
    ]
    for index, observation in enumerate(observations[-5:], start=1):
        lines.append(f"{index}. {observation[:800]}")
    lines.extend([
        "",
        "Limitations",
        "- Treat search-result snippets as leads, not confirmed page content.",
        "- Re-run with a more specific source or logged-in browser session if the target site blocks access.",
    ])
    return "\n".join(lines)


def _tool_evidence(state: AgentState) -> list[str]:
    evidence = []
    for message in state["messages"]:
        if not isinstance(message, ToolMessage):
            continue
        content = " ".join(str(message.content).split())
        if content and not _is_empty_tool_result(content):
            tool_name = message.name or "tool"
            evidence.append(f"{tool_name}: {content[:1200]}")
    return evidence


def _is_empty_tool_result(content: str) -> bool:
    lowered = content.strip().lower()
    return lowered in {'{"raw": ""}', "{'raw': ''}", "{}", "[]", ""}


def _format_evidence_block(evidence: list[str]) -> str:
    if not evidence:
        return "- No tool evidence was gathered."
    return "\n".join(f"- {item}" for item in evidence[-8:])


def _answer_ignores_evidence(answer: str, evidence: list[str]) -> bool:
    if not evidence:
        return False
    lowered = answer.lower()
    evidence_text = " ".join(evidence).lower()
    if "sources checked" in lowered and "- none" in lowered:
        return True
    if "no flight price information" in lowered and _evidence_contains_price_or_fare(evidence):
        return True
    if "no live price data" in lowered and _evidence_contains_price_or_fare(evidence):
        return True
    company_names = ("google", "amazon", "facebook", "meta", "microsoft", "apple", "netflix")
    if "company" in lowered or "companies" in lowered:
        invented_companies = [name for name in company_names if name in lowered and name not in evidence_text]
        if invented_companies:
            return True
    if "successfully executed" in lowered and not any(token in evidence_text for token in ("execution successful", "output", "stdout", "compiled successfully")):
        return True
    return False


def _evidence_contains_price_or_fare(evidence: list[str]) -> bool:
    joined = " ".join(evidence).lower()
    return "₹" in joined or "rs" in joined or "fare" in joined or "price" in joined or "flight" in joined


async def _finalize_session(state: AgentState, answer: str, evidence: Optional[list[str]] = None):
    evidence = evidence if evidence is not None else _tool_evidence(state)
    await complete_session(state["session_id"], answer)
    await record_task_summary(state["session_id"], state["goal"], answer, evidence)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
            else:
                text_parts.append(str(item))
        return next((part for part in reversed(text_parts) if part.strip()), "").strip()
    return str(content)


def _clean_answer(text: str) -> str:
    text = str(text or "")
    for token in ("<assistant>", "</assistant>", "<final>", "</final>"):
        text = text.replace(token, "")
    text = text.replace("siteis", "site is")
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return "\n".join(lines).strip()


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("act", act_node)
    g.add_node("observe", observe_node)
    g.add_node("summarise", summarise_node)
    g.set_entry_point("act")
    g.add_conditional_edges("act", should_continue, {"observe": "observe", "summarise": "summarise"})
    g.add_edge("observe", "act")
    g.add_edge("summarise", END)
    return g.compile()


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_agent(
    goal: str,
    session_id: Optional[str] = None,
    provider: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    session_id = session_id or str(uuid.uuid4())[:8]
    q: asyncio.Queue = asyncio.Queue()
    yield {"type": "status", "message": "Initialising agent…"}
    await create_session(session_id, goal, provider or os.getenv("AGENT_PROVIDER", "gemini"))
    await context_manager.create(session_id, goal, provider or os.getenv("AGENT_PROVIDER", "gemini"))
    memory_answer = await handle_memory_request(session_id, goal)
    if memory_answer:
        await complete_session(session_id, memory_answer)
        yield {"type": "done", "result": memory_answer}
        return
    memory_context = await recall_memory_context(session_id, goal)

    initial: AgentState = {
        "messages": [HumanMessage(content=goal)],
        "goal": goal,
        "session_id": session_id,
        "iteration": 0,
        "step_count": 0,
        "status_queue": q,
        "final_answer": None,
        "memory_context": memory_context,
    }
    config = RunnableConfig(configurable={"provider": provider})

    async def _run():
        try:
            await get_graph().ainvoke(initial, config=config)
        except Exception as e:
            logger.exception("Graph error")
            if _should_try_next_provider(e):
                await q.put({"type": "done", "result": (
                    "All configured LLM providers are currently unavailable, rate-limited, or out of credits. "
                    "OpenRouter free quota appears exhausted for this account today. "
                    "Try Gemini/Gemma, wait for quota reset, add OpenRouter credits, or add another provider key in .env."
                )})
            else:
                await q.put({"type": "error", "message": str(e)})
        finally:
            await q.put(None)

    task = asyncio.create_task(_run())
    while True:
        event = await q.get()
        if event is None:
            break
        yield event
    await task


def _describe(tool_name: str, args: dict) -> str:
    m = {
        "browse":     lambda a: f"Browsing {a.get('url','...')}",
        "scrape":     lambda a: f"Scraping {a.get('url','...')}",
        "search_web": lambda a: f"Searching: {a.get('query','...')}",
        "click":      lambda a: f"Clicking: {a.get('target','...')}",
        "type_text":  lambda a: f"Typing into {a.get('selector','input')}",
        "press_key":  lambda a: f"Pressing {a.get('key','Enter')}",
        "wait":       lambda a: f"Waiting {a.get('seconds', 2)}s",
        "page_state": lambda a: "Reading current page",
        "extract":    lambda a: f"Extracting: {a.get('instruction','...')}",
    }
    return m.get(tool_name, lambda a: f"Running {tool_name}")(args)


def _urls_from_text(text: str) -> list[str]:
    import re
    return [m.rstrip(".,)") for m in re.findall(r"https?://\S+", str(text))]


def _format_notes_for_summary(notes: dict) -> str:
    if not notes:
        return "none"
    lines = []
    for key in ("goal", "tried", "found", "pending", "best_so_far"):
        values = notes.get(key, [])
        if not values:
            lines.append(f"- {key}: none")
        else:
            lines.append(f"- {key}: " + "; ".join(str(v) for v in values[-8:]))
    return "\n".join(lines)
