from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.discord.database.connection import dispose_engine, set_engine_for_tests
from bot.discord.database.models import Base, SentMessage


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_engine_for_tests(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await dispose_engine()


def _old() -> datetime:
    return datetime.now(UTC) - timedelta(days=30)


def _fresh() -> datetime:
    return datetime.now(UTC)


async def _insert_sent(
    db, *, platform: str, recipient_id: str, created_at: datetime, kind: str = "dm"
) -> None:
    async with db.begin() as session:
        session.add(
            SentMessage(
                platform=platform,
                delivery_kind=kind,
                post_id="https://example.com/post/1",
                recipient_id=recipient_id,
                created_at=created_at,
            )
        )


async def _count(db) -> int:
    async with db() as session:
        return len((await session.execute(select(SentMessage.id))).all())


async def test_discord_user_deleted_via_delete_is_purged(db):
    from bot.discord.database.preferences import delete_preference, set_dm

    await set_dm(485079425931673600)
    await _insert_sent(db, platform="discord", recipient_id="485079425931673600", created_at=_old())

    assert await delete_preference(485079425931673600) is True

    from bot.retention import purge_expired_sent_messages

    removed = await purge_expired_sent_messages()
    assert removed == 1
    assert await _count(db) == 0


async def test_telegram_user_stopped_is_purged(db):
    from bot.retention import purge_expired_sent_messages
    from bot.telegram.database.users import delete_telegram_user, upsert_telegram_user

    await upsert_telegram_user(chat_id=1001, user_id=42)
    await _insert_sent(db, platform="telegram", recipient_id="1001", created_at=_old())

    assert await delete_telegram_user(1001) is True

    removed = await purge_expired_sent_messages()
    assert removed == 1
    assert await _count(db) == 0


async def test_active_discord_user_kept(db):
    from bot.discord.database.preferences import set_dm
    from bot.retention import purge_expired_sent_messages

    await set_dm(2001)
    await _insert_sent(db, platform="discord", recipient_id="2001", created_at=_old())

    assert await purge_expired_sent_messages() == 0
    assert await _count(db) == 1


async def test_fresh_row_within_retention_kept(db):
    from bot.retention import purge_expired_sent_messages

    await _insert_sent(db, platform="telegram", recipient_id="9999", created_at=_fresh())

    assert await purge_expired_sent_messages() == 0
    assert await _count(db) == 1


async def test_channel_kind_rows_untouched(db):
    from bot.retention import purge_expired_sent_messages

    await _insert_sent(
        db, platform="discord", recipient_id="777", created_at=_old(), kind="channel"
    )

    assert await purge_expired_sent_messages() == 0
    assert await _count(db) == 1
