from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from bot.discord.database.connection import get_session_factory

_STATUS = "PROCESSED"

_SELECT_COLUMNS = """
    id, title, url, vendor, author, published_at, created_at, status, ai_result
"""


def _posts_table(dialect_name: str) -> str:
    base = "posts"
    return f"public.{base}" if dialect_name == "postgresql" else base


def _coerce_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    ai_result = data.get("ai_result")
    if isinstance(ai_result, str):
        try:
            data["ai_result"] = json.loads(ai_result)
        except (json.JSONDecodeError, TypeError):
            data["ai_result"] = None
    return data


async def fetch_latest_posts(limit: int = 1, status: str = _STATUS) -> list[dict[str, Any]]:
    """Read the most recent PROCESSED rows from the app's posts table."""
    async with get_session_factory()() as session:
        table = _posts_table(session.get_bind().dialect.name)
        result = await session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM {table} "
                "WHERE status = :status "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"status": status, "limit": limit},
        )
        rows = result.mappings().all()
        return [_coerce_row(r) for r in rows]


async def fetch_post(post_id: str) -> dict[str, Any] | None:
    """Read a single row by id, if present."""
    async with get_session_factory()() as session:
        table = _posts_table(session.get_bind().dialect.name)
        result = await session.execute(
            text(f"SELECT {_SELECT_COLUMNS} FROM {table} WHERE id = :post_id"),
            {"post_id": post_id},
        )
        row = result.mappings().first()
        return _coerce_row(row) if row else None
