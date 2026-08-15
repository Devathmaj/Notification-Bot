from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.discord.database.models import Base
from config import settings

logger = logging.getLogger("discord.bot.schema")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def app_tables_exist() -> bool:
    """Return True when our schema already exists (used to skip DDL for DML-only users)."""
    engine = get_engine()
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("preferences")
        )


def _schema_current(sync_conn) -> bool:
    """True when the owned tables already match the models (nothing to upgrade)."""
    insp = inspect(sync_conn)
    if not insp.has_table("channel_targets"):
        return False
    prefs_cols = {c["name"] for c in insp.get_columns("preferences")}
    sent_cols = {c["name"] for c in insp.get_columns("sent_messages")}
    if "dm_enabled" not in prefs_cols or "recipient_id" not in sent_cols:
        return False
    if "telegram_message_id" not in sent_cols:
        return False
    post_id_len = next(
        (
            c["type"].length
            for c in insp.get_columns("sent_messages")
            if c["name"] == "post_id"
        ),
        None,
    )
    if post_id_len is not None and post_id_len < 512:
        return False
    return True


async def ensure_schema() -> None:
    """Create owned tables if missing (CREATE TABLE IF NOT EXISTS).

    Runs DDL only when the tables do not exist yet, so a DML-only app role can
    start safely on subsequent runs. Also grants DML on our tables to DB_APP_USER
    on first run.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        created = not await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("preferences")
        )
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))

        if not created and not await conn.run_sync(_schema_current):
            # Schema upgrades for tables created before these changes. All
            # statements are idempotent; a DML-only role cannot run DDL, so
            # ignore failures rather than crash the boot.
            try:
                # Discord snowflake IDs exceed INT4, widen key columns to BIGINT.
                await conn.execute(
                    text("ALTER TABLE sent_messages ALTER COLUMN preference_id TYPE bigint")
                )
                await conn.execute(
                    text("ALTER TABLE preferences ALTER COLUMN user_id TYPE bigint")
                )
                # post_id now carries announcement URLs, which exceed the old
                # 64-char integer column.
                await conn.execute(
                    text(
                        "ALTER TABLE sent_messages ALTER COLUMN post_id TYPE varchar(512)"
                    )
                )
                # Channel feeds moved to their own per-channel table; preface
                # preferences now only holds the per-user DM flag.
                await conn.execute(
                    text(
                        "ALTER TABLE preferences ADD COLUMN IF NOT EXISTS "
                        "dm_enabled boolean NOT NULL DEFAULT false"
                    )
                )
                await conn.execute(
                    text("ALTER TABLE preferences DROP COLUMN IF EXISTS delivery_method")
                )
                await conn.execute(
                    text(
                        "ALTER TABLE preferences DROP COLUMN IF EXISTS notify_everyone"
                    )
                )
                await conn.execute(
                    text("ALTER TABLE preferences DROP COLUMN IF EXISTS channel_enabled")
                )
                await conn.execute(
                    text("ALTER TABLE preferences DROP COLUMN IF EXISTS guild_id")
                )
                await conn.execute(
                    text("ALTER TABLE preferences DROP COLUMN IF EXISTS channel_id")
                )
                await conn.execute(
                    text("ALTER TABLE preferences DROP COLUMN IF EXISTS mention")
                )
                # Dedup per (platform, kind, post, recipient): recipient is a
                # user snowflake for DMs, a channel snowflake for feeds.
                await conn.execute(
                    text(
                        "ALTER TABLE sent_messages ADD COLUMN IF NOT EXISTS "
                        "delivery_kind varchar(10) NOT NULL DEFAULT 'dm'"
                    )
                )
                # Optional outbound message id recorded for Telegram deliveries.
                await conn.execute(
                    text(
                        "ALTER TABLE sent_messages ADD COLUMN IF NOT EXISTS "
                        "telegram_message_id varchar(40)"
                    )
                )
                await conn.execute(
                    text(
                        "ALTER TABLE sent_messages ADD COLUMN IF NOT EXISTS "
                        "recipient_id varchar(40)"
                    )
                )
                # Backfill recipient_id from the legacy user_id column, but only
                # while that column still exists (it is dropped below); on an
                # already-upgraded table this is a no-op.
                await conn.execute(
                    text(
                        "DO $$ BEGIN "
                        "IF EXISTS (SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'sent_messages' "
                        "AND column_name = 'user_id') THEN "
                        "UPDATE sent_messages SET recipient_id = user_id::text "
                        "WHERE recipient_id IS NULL AND delivery_kind = 'dm'; "
                        "END IF; END $$"
                    )
                )
                await conn.execute(
                    text(
                        "ALTER TABLE sent_messages DROP CONSTRAINT "
                        "IF EXISTS uq_sent_platform_post_user"
                    )
                )
                await conn.execute(
                    text(
                        "ALTER TABLE sent_messages DROP CONSTRAINT "
                        "IF EXISTS uq_sent_kind_platform_post_user"
                    )
                )
                await conn.execute(
                    text("ALTER TABLE sent_messages DROP COLUMN IF EXISTS user_id")
                )
                await conn.execute(
                    text(
                        "DO $$ BEGIN "
                        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
                        "WHERE conname = 'uq_sent_kind_platform_post_recipient') THEN "
                        "ALTER TABLE sent_messages ADD CONSTRAINT "
                        "uq_sent_kind_platform_post_recipient "
                        "UNIQUE (platform, delivery_kind, post_id, recipient_id); "
                        "END IF; END $$"
                    )
                )
            except Exception:
                logger.warning("Could not apply schema upgrades (ignoring)", exc_info=True)

        if created and settings.db_app_user:
            role = settings.db_app_user
            await conn.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                    f'preferences, sent_messages, channel_targets, telegram_users, '
                    f'telegram_groups TO "{role}"'
                )
            )
            await conn.execute(
                text(
                    f"GRANT USAGE, SELECT ON SEQUENCE sent_messages_id_seq, "
                    f'channel_targets_id_seq TO "{role}"'
                )
            )


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def set_engine_for_tests(engine: AsyncEngine) -> None:
    """Override the global engine (used by tests with an in-memory SQLite engine)."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
