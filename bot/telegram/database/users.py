from __future__ import annotations

from sqlalchemy import select

from bot.discord.database.connection import get_session_factory
from bot.telegram.database.models import TelegramUser


async def upsert_telegram_user(
    chat_id: int,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    subscribed: bool = True,
) -> TelegramUser:
    """Create or refresh a private-chat subscription (used on /start)."""
    async with get_session_factory()() as session:
        user = await session.get(TelegramUser, chat_id)
        if user is None:
            user = TelegramUser(chat_id=chat_id)
            session.add(user)
        user.user_id = user_id
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.subscribed = subscribed
        await session.commit()
        await session.refresh(user)
        return user


async def get_telegram_user(chat_id: int) -> TelegramUser | None:
    async with get_session_factory()() as session:
        return await session.get(TelegramUser, chat_id)


async def list_telegram_users(subscribed: bool | None = True) -> list[TelegramUser]:
    async with get_session_factory()() as session:
        stmt = select(TelegramUser)
        if subscribed is not None:
            stmt = stmt.where(TelegramUser.subscribed.is_(subscribed))
        result = await session.execute(stmt)
        return list(result.scalars().all())
