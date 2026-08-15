from __future__ import annotations

from sqlalchemy import select

from bot.discord.database.connection import get_session_factory
from bot.telegram.database.models import TelegramGroup


async def upsert_telegram_group(
    chat_id: int,
    title: str | None = None,
    chat_type: str | None = None,
    active: bool = True,
) -> TelegramGroup:
    """Create or refresh a chat the bot is present in (fired on being added)."""
    async with get_session_factory()() as session:
        group = await session.get(TelegramGroup, chat_id)
        if group is None:
            group = TelegramGroup(chat_id=chat_id)
            session.add(group)
        group.title = title
        group.chat_type = chat_type or group.chat_type or "unknown"
        group.active = active
        await session.commit()
        await session.refresh(group)
        return group


async def deactivate_telegram_group(chat_id: int) -> bool:
    """Mark a chat inactive after the bot is removed from it."""
    async with get_session_factory()() as session:
        group = await session.get(TelegramGroup, chat_id)
        if group is None:
            return False
        group.active = False
        await session.commit()
        return True


async def list_active_groups() -> list[TelegramGroup]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(TelegramGroup).where(TelegramGroup.active.is_(True))
        )
        return list(result.scalars().all())
