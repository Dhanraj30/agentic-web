"""
Memory — AgenticWeb
SQLite-backed session and step memory.
"""
from __future__ import annotations
import aiosqlite
import json
import re
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "memory.db"


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return aiosqlite.connect(DB_PATH)


async def init_db():
    async with _db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                goal TEXT, provider TEXT,
                created_at REAL, status TEXT DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, step_num INTEGER,
                tool TEXT, action TEXT, args TEXT,
                result TEXT, status TEXT, ts REAL
            );
            CREATE TABLE IF NOT EXISTS facts (
                session_id TEXT, key TEXT, value TEXT, ts REAL,
                PRIMARY KEY (session_id, key)
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                kind TEXT,
                content TEXT,
                metadata TEXT,
                ts REAL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_items_session_ts
                ON memory_items(session_id, ts DESC);
        """)
        await db.commit()


async def create_session(session_id: str, goal: str, provider: str):
    await init_db()
    fact = _extract_fact(goal)
    async with _db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)",
            (session_id, goal, provider, time.time(), "active"),
        )
        await db.execute(
            "INSERT INTO memory_items (session_id,kind,content,metadata,ts) VALUES (?,?,?,?,?)",
            (session_id, "goal", goal[:2000], json.dumps({"provider": provider}), time.time()),
        )
        if fact:
            key, value = fact
            await db.execute(
                "INSERT OR REPLACE INTO facts VALUES (?,?,?,?)",
                (session_id, key, value, time.time()),
            )
        await db.commit()


async def log_step(session_id: str, step_num: int, tool: str, action: str,
                   args: dict, result: str, status: str = "done"):
    async with _db() as db:
        await db.execute(
            "INSERT INTO steps (session_id,step_num,tool,action,args,result,status,ts) VALUES (?,?,?,?,?,?,?,?)",
            (session_id, step_num, tool, action, json.dumps(args), result[:2000], status, time.time()),
        )
        await db.commit()


async def remember(session_id: str, key: str, value: str):
    await init_db()
    async with _db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO facts VALUES (?,?,?,?)",
            (session_id, key, value, time.time()),
        )
        await db.commit()


async def recall(session_id: str, key: str) -> str:
    await init_db()
    async with _db() as db:
        cur = await db.execute(
            "SELECT value FROM facts WHERE session_id=? AND key=?",
            (session_id, key),
        )
        row = await cur.fetchone()
        return row[0] if row else ""


async def get_step_history(session_id: str, limit: int = 20) -> list[dict]:
    await init_db()
    async with _db() as db:
        cur = await db.execute(
            "SELECT step_num,tool,action,result,status FROM steps "
            "WHERE session_id=? ORDER BY step_num DESC LIMIT ?",
            (session_id, limit),
        )
        rows = await cur.fetchall()
        return [{"step": r[0], "tool": r[1], "action": r[2],
                 "result": r[3], "status": r[4]} for r in reversed(rows)]


async def complete_session(session_id: str, final_answer: str | None = None):
    await init_db()
    async with _db() as db:
        await db.execute(
            "UPDATE sessions SET status='complete' WHERE session_id=?",
            (session_id,),
        )
        if final_answer:
            await db.execute(
                "INSERT INTO memory_items (session_id,kind,content,metadata,ts) VALUES (?,?,?,?,?)",
                (session_id, "answer", final_answer[:4000], "{}", time.time()),
            )
        await db.commit()


async def record_task_summary(session_id: str, goal: str, answer: str, evidence: list[str]):
    await init_db()
    if _is_bad_memory(answer):
        return
    content = "\n".join([
        f"Goal: {goal}",
        f"Answer: {answer[:2500]}",
        "Evidence:",
        *[item[:700] for item in evidence[-6:]],
    ])
    async with _db() as db:
        await db.execute(
            "INSERT INTO memory_items (session_id,kind,content,metadata,ts) VALUES (?,?,?,?,?)",
            (
                session_id,
                "task_summary",
                content[:5000],
                json.dumps({"evidence_count": len(evidence)}),
                time.time(),
            ),
        )
        await db.commit()


async def recall_memory_context(session_id: str, goal: str, limit: int = 8) -> str:
    await init_db()
    query_tokens = _tokens(goal)
    async with _db() as db:
        cur = await db.execute(
            "SELECT kind,content,ts FROM memory_items "
            "WHERE session_id=? ORDER BY ts DESC LIMIT 80",
            (session_id,),
        )
        rows = await cur.fetchall()

        fact_cur = await db.execute(
            "SELECT key,value,ts FROM facts WHERE session_id=? ORDER BY ts DESC LIMIT 30",
            (session_id,),
        )
        facts = await fact_cur.fetchall()

    scored = []
    for kind, content, ts in rows:
        if _is_bad_memory(content):
            continue
        score = _score(query_tokens, content)
        recency_bonus = max(0.0, 1.0 - ((time.time() - float(ts)) / 86400.0)) if ts else 0.0
        scored.append((score + recency_bonus, kind, content))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [item for item in scored if item[0] > 0][:limit]
    if not selected:
        selected = scored[: min(3, len(scored))]

    lines: list[str] = []
    if selected:
        lines.append("Relevant memory from this user session:")
        for _, kind, content in selected:
            lines.append(f"- {kind}: {_compact(content, 700)}")

    if facts:
        lines.append("Stored user facts/preferences:")
        for key, value, _ in facts[:8]:
            lines.append(f"- {key}: {_compact(value, 300)}")

    if not lines:
        return ""

    return "\n".join([
        "Use this memory only when it is relevant to the current user request.",
        "Do not claim there is no previous context if memory is provided.",
        *lines,
    ])


async def handle_memory_request(session_id: str, goal: str) -> str | None:
    fact = _extract_fact(goal)
    if fact and _looks_like_remember_command(goal):
        key, value = fact
        await remember(session_id, key, value)
        return f"Got it. I will remember that your {key} is {value}."

    if not _looks_like_memory_question(goal):
        return None

    query_tokens = _tokens(goal)
    async with _db() as db:
        cur = await db.execute(
            "SELECT key,value FROM facts WHERE session_id=?",
            (session_id,),
        )
        facts = await cur.fetchall()

    if not facts:
        return None

    best = None
    best_score = -1.0
    for key, value in facts:
        score = _score(query_tokens, key)
        if score > best_score:
            best = (key, value)
            best_score = score

    if best and best_score > 0:
        key, value = best
        return f"Your {key} is {value}."
    return None


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t not in _STOPWORDS}


def _score(query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = _tokens(content)
    if not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / max(1, len(query_tokens))


def _compact(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def _extract_fact(text: str) -> tuple[str, str] | None:
    raw = " ".join(str(text).strip().split())
    if not _looks_like_remember_command(raw):
        return None
    cleaned = re.sub(r"^remember(?: for this session)?[:\s-]*", "", raw, flags=re.I)
    match = re.search(r"^(?:my\s+)?(?P<key>[a-z0-9][a-z0-9\s_-]{2,80}?)\s+(?:is|=)\s+(?P<value>[^.?!]+)", cleaned, re.I)
    if not match:
        return None
    key = match.group("key").strip().lower()
    value = match.group("value").strip()
    key = re.sub(r"^(my|the)\s+", "", key)
    return key, value


def _looks_like_remember_command(text: str) -> bool:
    return str(text).strip().lower().startswith("remember")


def _looks_like_memory_question(text: str) -> bool:
    lowered = str(text).lower()
    return (
        "from memory" in lowered
        or "what is my" in lowered
        or "what did i" in lowered
        or "do you remember" in lowered
        or "previous session" in lowered
        or "previous conversation" in lowered
    )


def _is_bad_memory(text: str) -> bool:
    lowered = str(text).lower()
    return (
        "don't have access to your memory" in lowered
        or "do not have access to your memory" in lowered
        or "don't have access to previous sessions" in lowered
        or "do not have access to previous sessions" in lowered
    )


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "what",
    "when", "where", "which", "your", "you", "are", "was", "were", "can",
    "able", "need", "help", "please", "about", "into", "only", "using",
}
