from __future__ import annotations

from sqlalchemy import delete, select

from bot.discord.database.connection import get_session_factory
from bot.discord.database.models import DeliveryMethod, SentMessage
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


async def delete_telegram_group(chat_id: int) -> bool:
    """Erase a chat row when the bot is removed from it (right to erasure)."""
    async with get_session_factory()() as session:
        group = await session.get(TelegramGroup, chat_id)
        if group is None:
            return False
        await session.delete(group)
        await session.commit()
        return True


async def list_active_groups() -> list[TelegramGroup]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(TelegramGroup).where(TelegramGroup.active.is_(True))
        )
        return list(result.scalars().all())


async def purge_group_sent_history(chat_id: int) -> int:
    """Delete a group's sent-message history when the bot is removed from it."""
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(SentMessage).where(
                SentMessage.platform == "telegram",
                SentMessage.delivery_kind == DeliveryMethod.channel,
                SentMessage.recipient_id == str(chat_id),
            )
        )
        await session.commit()
        return result.rowcount or 0
