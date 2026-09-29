"""SQLite 存储层（标准库 sqlite3，线程安全封装）。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

DB_PATH = Path(__file__).resolve().parent / "data" / "plans.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect()
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                status TEXT NOT NULL,
                used_area INTEGER NOT NULL,
                total_cuts INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        _conn.commit()
    return _conn


def save_plan(name: str, request: dict, response: dict) -> int:
    conn = get_conn()
    with _lock:
        cur = conn.execute(
            "INSERT INTO plans(name, request_json, response_json, status,"
            " used_area, total_cuts, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, json.dumps(request, ensure_ascii=False),
             json.dumps(response, ensure_ascii=False),
             response.get("status"), response.get("used_area", 0),
             response.get("total_cuts", 0),
             datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        return int(cur.lastrowid)


def list_plans() -> List[dict]:
    conn = get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id, name, status, used_area, total_cuts, created_at "
            "FROM plans ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_plan(plan_id: int) -> Optional[dict]:
    conn = get_conn()
    with _lock:
        row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["request"] = json.loads(d.pop("request_json"))
    d["response"] = json.loads(d.pop("response_json"))
    return d


def delete_plan(plan_id: int) -> bool:
    conn = get_conn()
    with _lock:
        cur = conn.execute("DELETE FROM plans WHERE id=?", (plan_id,))
        conn.commit()
        return cur.rowcount > 0
