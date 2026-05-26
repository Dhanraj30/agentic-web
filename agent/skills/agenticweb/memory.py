"""
Memory — AgenticWeb
SQLite-backed session and step memory.
"""
from __future__ import annotations
import aiosqlite
import json
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
        """)
        await db.commit()


async def create_session(session_id: str, goal: str, provider: str):
    await init_db()
    async with _db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)",
            (session_id, goal, provider, time.time(), "active"),
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
    async with _db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO facts VALUES (?,?,?,?)",
            (session_id, key, value, time.time()),
        )
        await db.commit()


async def recall(session_id: str, key: str) -> str:
    async with _db() as db:
        cur = await db.execute(
            "SELECT value FROM facts WHERE session_id=? AND key=?",
            (session_id, key),
        )
        row = await cur.fetchone()
        return row[0] if row else ""


async def get_step_history(session_id: str, limit: int = 20) -> list[dict]:
    async with _db() as db:
        cur = await db.execute(
            "SELECT step_num,tool,action,result,status FROM steps "
            "WHERE session_id=? ORDER BY step_num DESC LIMIT ?",
            (session_id, limit),
        )
        rows = await cur.fetchall()
        return [{"step": r[0], "tool": r[1], "action": r[2],
                 "result": r[3], "status": r[4]} for r in reversed(rows)]


async def complete_session(session_id: str):
    async with _db() as db:
        await db.execute(
            "UPDATE sessions SET status='complete' WHERE session_id=?",
            (session_id,),
        )
        await db.commit()
