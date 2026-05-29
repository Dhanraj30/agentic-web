"""
Context manager for AgenticWeb.

Keeps a compact, structured view of session progress while preserving the
existing LangGraph message flow for tool calling.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .memory import load_context_notes, load_context_references, save_context_notes, save_context_reference


NOTE_KEYS = ("goal", "tried", "found", "pending", "best_so_far")


@dataclass
class SessionContext:
    session_id: str
    goal: str
    provider: str
    notes: dict[str, list[str]]
    references: list[dict] = field(default_factory=list)
    message_history: list[BaseMessage] = field(default_factory=list)
    compacted_summary: str = ""
    step_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)


class ContextManager:
    def __init__(self):
        self._sessions: dict[str, SessionContext] = {}

    async def create(self, session_id: str, goal: str, provider: str) -> SessionContext:
        notes = _empty_notes(goal)
        saved_notes = await load_context_notes(session_id)
        if saved_notes:
            notes = _normalise_notes(saved_notes, goal)

        refs = await load_context_references(session_id)
        ctx = SessionContext(
            session_id=session_id,
            goal=goal,
            provider=provider,
            notes=notes,
            references=refs,
            message_history=[HumanMessage(content=goal)],
        )
        self._sessions[session_id] = ctx
        await save_context_notes(session_id, ctx.notes)
        return ctx

    def get(self, session_id: str) -> Optional[SessionContext]:
        return self._sessions.get(session_id)

    async def update_notes(self, session_id: str, last_tool_result: str, tool_name: str) -> None:
        ctx = self.get(session_id)
        if not ctx:
            return

        result = " ".join(str(last_tool_result or "").split())
        if not result or _is_empty_result(result):
            _append_unique(ctx.notes["tried"], f"{tool_name} returned no usable data")
            ctx.last_updated = time.time()
            await save_context_notes(session_id, ctx.notes)
            return

        _append_unique(ctx.notes["tried"], _describe_attempt(tool_name, result))
        for fact in _extract_specific_facts(result):
            _append_unique(ctx.notes["found"], fact)

        best = _best_candidate(result)
        if best:
            ctx.notes["best_so_far"] = [best]

        ctx.notes["pending"] = _derive_pending(ctx.notes)
        ctx.last_updated = time.time()
        await save_context_notes(session_id, ctx.notes)

    async def add_reference(self, session_id: str, ref_type: str, value: str, label: str) -> None:
        ctx = self.get(session_id)
        if not ctx or not value:
            return
        existing = next((r for r in ctx.references if r.get("value") == value), None)
        if existing:
            existing.update({"type": ref_type, "label": label or existing.get("label", ""), "used": existing.get("used", False)})
            ref = existing
        else:
            ref = {"type": ref_type, "value": value, "label": label or value, "used": False}
            ctx.references.append(ref)
        ctx.last_updated = time.time()
        await save_context_reference(session_id, ref)

    async def mark_reference_used(self, session_id: str, value: str) -> None:
        ctx = self.get(session_id)
        if not ctx or not value:
            return
        for ref in ctx.references:
            if ref.get("value") == value:
                ref["used"] = True
                ref["updated_at"] = time.time()
                await save_context_reference(session_id, ref)
                break

    def is_reference_used(self, session_id: str, value: str) -> bool:
        ctx = self.get(session_id)
        if not ctx:
            return False
        return any(ref.get("value") == value and ref.get("used") for ref in ctx.references)

    def get_context_block(self, session_id: str) -> str:
        ctx = self.get(session_id)
        if not ctx:
            return ""
        notes = ctx.notes
        unused = [r for r in ctx.references if not r.get("used")]
        return "\n".join([
            "=== SESSION MEMORY ===",
            f"Goal: {ctx.goal}",
            "",
            "Notes:",
            f"  Tried: {_bullets(notes.get('tried', []))}",
            f"  Found: {_bullets(notes.get('found', []))}",
            f"  Pending: {_bullets(notes.get('pending', []))}",
            f"  Best so far: {_bullets(notes.get('best_so_far', []))}",
            "",
            "References (unused):",
            _reference_lines(unused),
            "",
            f"Steps completed: {ctx.step_count}",
            "=== END MEMORY ===",
        ])

    def should_compact(self, session_id: str) -> bool:
        ctx = self.get(session_id)
        if not ctx:
            return False
        chars = sum(len(str(getattr(m, "content", ""))) for m in ctx.message_history)
        return len(ctx.message_history) > 20 or chars // 4 > 12000

    async def compact(self, session_id: str, llm_router: Any = None) -> str:
        ctx = self.get(session_id)
        if not ctx:
            return ""
        summary = "\n".join([
            f"Original goal: {ctx.goal}",
            f"Tried: {'; '.join(ctx.notes.get('tried', [])[-10:]) or 'none'}",
            f"Found: {'; '.join(ctx.notes.get('found', [])[-12:]) or 'none'}",
            f"Pending: {'; '.join(ctx.notes.get('pending', [])[-8:]) or 'none'}",
            f"Best so far: {'; '.join(ctx.notes.get('best_so_far', [])[-3:]) or 'none'}",
        ])
        ctx.compacted_summary = summary
        ctx.message_history = ctx.message_history[-5:]
        ctx.last_updated = time.time()
        await save_context_notes(session_id, ctx.notes)
        return summary

    def build_messages_for_llm(self, session_id: str, system_prompt: str) -> list[BaseMessage]:
        ctx = self.get(session_id)
        if not ctx:
            return [SystemMessage(content=system_prompt)]

        system = f"{system_prompt}\n\n{self.get_context_block(session_id)}"
        messages: list[BaseMessage] = [SystemMessage(content=system)]
        if ctx.compacted_summary:
            messages.extend([
                HumanMessage(content=f"Previous session summary:\n{ctx.compacted_summary}"),
                AIMessage(content="Understood. Continuing from where I left off."),
            ])
        messages.extend(ctx.message_history[-5:])
        return messages

    def append_message(self, session_id: str, message: BaseMessage) -> None:
        ctx = self.get(session_id)
        if not ctx:
            return
        ctx.message_history.append(message)
        ctx.last_updated = time.time()

    def as_dict(self, session_id: str) -> dict:
        ctx = self.get(session_id)
        if not ctx:
            return {}
        return {
            "session_id": ctx.session_id,
            "goal": ctx.goal,
            "provider": ctx.provider,
            "notes": ctx.notes,
            "references": ctx.references,
            "message_history_count": len(ctx.message_history),
            "compacted_summary": ctx.compacted_summary,
            "step_count": ctx.step_count,
            "created_at": ctx.created_at,
            "last_updated": ctx.last_updated,
        }


def parse_references_from_search_result(text: str) -> list[dict]:
    refs = []
    for line in str(text).splitlines():
        match = re.match(r"\[(\d+)\]\s+(.+?)\s+[—|-]\s+(https?://\S+)", line.strip())
        if match:
            refs.append({"type": "url", "label": match.group(2).strip(), "value": match.group(3).strip()})
    return refs


def _empty_notes(goal: str) -> dict[str, list[str]]:
    return {"goal": [goal], "tried": [], "found": [], "pending": [], "best_so_far": []}


def _normalise_notes(notes: dict, goal: str) -> dict[str, list[str]]:
    normalised = _empty_notes(goal)
    for key in NOTE_KEYS:
        value = notes.get(key, [])
        normalised[key] = value if isinstance(value, list) else [str(value)]
    normalised["goal"] = [goal]
    return normalised


def _append_unique(items: list[str], value: str, limit: int = 30) -> None:
    value = str(value).strip()
    if value and value not in items:
        items.append(value)
    del items[:-limit]


def _describe_attempt(tool_name: str, result: str) -> str:
    if tool_name == "search_web":
        return f"Searched web; top result: {result[:180]}"
    if tool_name in {"browse", "scrape"}:
        url = _first_url(result)
        return f"{tool_name} checked {url or result[:160]}"
    return f"{tool_name} ran; result snippet: {result[:160]}"


def _extract_specific_facts(text: str) -> list[str]:
    facts: list[str] = []
    for url in re.findall(r"https?://\S+", text):
        facts.append(f"URL: {url.rstrip(').,')}")
    for price in re.findall(r"(?:₹|INR|Rs\.?)\s?[0-9][0-9,]*(?:\.\d+)?", text, flags=re.I):
        facts.append(f"Price/fare text: {price}")
    for line in text.split(". "):
        if re.search(r"\b(?:flight|fare|price|hotel|gold|news|source)\b", line, re.I) and len(line) < 220:
            facts.append(line.strip())
    return facts[:12]


def _best_candidate(text: str) -> str:
    price_match = re.search(r"(.{0,120}(?:₹|INR|Rs\.?)\s?[0-9][0-9,]*(?:\.\d+)?.{0,120})", text, re.I)
    if price_match:
        return price_match.group(1).strip()
    return ""


def _derive_pending(notes: dict[str, list[str]]) -> list[str]:
    found_text = " ".join(notes.get("found", [])).lower()
    pending = []
    if "price" in found_text or "fare" in found_text or "₹" in found_text:
        pending.append("Verify whether listed prices are live and date-specific.")
    elif notes.get("goal"):
        pending.append("Gather specific factual data from reliable sources.")
    return pending[:8]


def _bullets(items: list[str]) -> str:
    if not items:
        return "none"
    return "\n    - " + "\n    - ".join(items[-8:])


def _reference_lines(refs: list[dict]) -> str:
    if not refs:
        return "  none"
    return "\n".join(f"  - [{r.get('type', 'url')}] {r.get('label', '')}: {r.get('value', '')}" for r in refs[-10:])


def _is_empty_result(content: str) -> bool:
    return content.strip().lower() in {'{"raw": ""}', "{'raw': ''}", "{}", "[]"}


def _first_url(text: str) -> str:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip(".,)") if match else ""
