from __future__ import annotations

from sqlalchemy import delete, select

from bot.discord.database.connection import get_session_factory
from bot.discord.database.models import Preference


async def set_dm(user_id: int) -> Preference:
    """Enable DM delivery for a user."""
    async with get_session_factory()() as session:
        pref = await session.get(Preference, user_id)
        if pref is None:
            pref = Preference(user_id=user_id)
            session.add(pref)
        pref.dm_enabled = True
        await session.commit()
        await session.refresh(pref)
        return pref


async def disable_dm(user_id: int) -> Preference | None:
    async with get_session_factory()() as session:
        pref = await session.get(Preference, user_id)
        if pref is None:
            return None
        pref.dm_enabled = False
        await session.commit()
        await session.refresh(pref)
        return pref


async def get_preference(user_id: int) -> Preference | None:
    async with get_session_factory()() as session:
        return await session.get(Preference, user_id)


async def list_preferences() -> list[Preference]:
    async with get_session_factory()() as session:
        result = await session.execute(select(Preference))
        return list(result.scalars().all())


async def delete_preference(user_id: int) -> bool:
    async with get_session_factory()() as session:
        result = await session.execute(delete(Preference).where(Preference.user_id == user_id))
        await session.commit()
        return result.rowcount > 0
