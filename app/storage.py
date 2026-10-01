from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS token_store (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                open_id TEXT,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                scope TEXT,
                expires_at INTEGER NOT NULL,
                refresh_expires_at INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS queued_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stored_path TEXT NOT NULL,
                original_name TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                planned_for TEXT,
                status TEXT NOT NULL DEFAULT 'READY',
                publish_id TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def save_tokens(payload: dict[str, Any]) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    expires_in = int(payload.get("expires_in", 0))
    refresh_expires_in = int(payload.get("refresh_expires_in", 0))
    with _connect() as con:
        con.execute(
            """
            INSERT INTO token_store(
                singleton, open_id, access_token, refresh_token, scope,
                expires_at, refresh_expires_at, updated_at
            ) VALUES(1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                open_id=excluded.open_id,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                scope=excluded.scope,
                expires_at=excluded.expires_at,
                refresh_expires_at=excluded.refresh_expires_at,
                updated_at=excluded.updated_at
            """,
            (
                payload.get("open_id"),
                payload["access_token"],
                payload["refresh_token"],
                payload.get("scope", ""),
                now + expires_in,
                now + refresh_expires_in,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_tokens() -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute("SELECT * FROM token_store WHERE singleton=1").fetchone()
    return dict(row) if row else None


def clear_tokens() -> None:
    with _connect() as con:
        con.execute("DELETE FROM token_store WHERE singleton=1")


def add_queue_item(stored_path: str, original_name: str, title: str, planned_for: str | None) -> int:
    with _connect() as con:
        cur = con.execute(
            """
            INSERT INTO queued_posts(stored_path, original_name, title, planned_for, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (stored_path, original_name, title, planned_for, datetime.now(timezone.utc).isoformat()),
        )
        return int(cur.lastrowid)


def list_queue() -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM queued_posts ORDER BY COALESCE(planned_for, created_at), id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_queue_item(item_id: int) -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute("SELECT * FROM queued_posts WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def update_queue_item(item_id: int, **fields: Any) -> None:
    allowed = {"status", "publish_id", "last_error", "title", "planned_for"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    assignments = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [item_id]
    with _connect() as con:
        con.execute(f"UPDATE queued_posts SET {assignments} WHERE id=?", values)


def delete_queue_item(item_id: int) -> str | None:
    item = get_queue_item(item_id)
    if not item:
        return None
    with _connect() as con:
        con.execute("DELETE FROM queued_posts WHERE id=?", (item_id,))
    path = Path(item["stored_path"])
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return str(path)
