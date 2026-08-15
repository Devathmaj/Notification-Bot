from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.discord.database.connection import dispose_engine, set_engine_for_tests
from bot.discord.database.posts import fetch_latest_posts, fetch_post


@pytest.fixture
async def posts_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE posts ("
                "id INTEGER PRIMARY KEY, title TEXT, url TEXT, vendor TEXT, author TEXT, "
                "published_at TEXT, created_at TEXT, status TEXT, ai_result TEXT)"
            )
        )
        for i, status in enumerate(["PROCESSED", "PROCESSED", "NEW", "PROCESSED"], start=1):
            await conn.execute(
                text(
                    "INSERT INTO posts "
                    "(id, title, url, vendor, author, published_at, created_at, status, ai_result) "
                    "VALUES (:id, :title, :url, :vendor, :author, :published_at, :created_at, "
                    ":status, :ai_result)"
                ),
                {
                    "id": i,
                    "title": f"Post {i}",
                    "url": f"https://example.com/post/{i}",
                    "vendor": "aws",
                    "author": "Author",
                    "published_at": f"2026-08-1{i}T10:00:00+00:00",
                    "created_at": f"2026-08-1{i}T10:00:00+00:00",
                    "status": status,
                    "ai_result": f'{{"confidence": 0.{i}}}',
                },
            )
    set_engine_for_tests(engine)
    yield engine
    await dispose_engine()


async def test_fetch_latest_posts_filters_processed(posts_db):
    posts = await fetch_latest_posts(limit=10)
    assert [p["title"] for p in posts] == ["Post 4", "Post 2", "Post 1"]  # NEW post 3 skipped


async def test_fetch_latest_post_limit_1(posts_db):
    posts = await fetch_latest_posts(limit=1)
    assert len(posts) == 1
    assert posts[0]["title"] == "Post 4"


async def test_fetch_post_by_id(posts_db):
    post = await fetch_post("2")
    assert post is not None
    assert post["status"] == "PROCESSED"
    assert post["ai_result"]["confidence"] == 0.2
