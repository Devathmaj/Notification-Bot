from __future__ import annotations

from sqlalchemy import delete, select

from bot.discord.database.connection import get_session_factory
from bot.discord.database.models import ChannelTarget, DeliveryMethod, SentMessage


async def upsert_channel_target(
    guild_id: str,
    channel_id: str,
    set_by_user_id: int,
    mention: str = "none",
) -> ChannelTarget:
    """Create or reconfigure the single feed for a channel."""
    async with get_session_factory()() as session:
        target = (
            await session.execute(
                select(ChannelTarget).where(
                    ChannelTarget.guild_id == guild_id,
                    ChannelTarget.channel_id == channel_id,
                )
            )
        ).scalar_one_or_none()
        if target is None:
            target = ChannelTarget(
                guild_id=guild_id,
                channel_id=channel_id,
                set_by_user_id=set_by_user_id,
                mention=mention,
            )
            session.add(target)
        else:
            target.set_by_user_id = set_by_user_id
            target.mention = mention
        await session.commit()
        await session.refresh(target)
        return target


async def get_channel_target(guild_id: str, channel_id: str) -> ChannelTarget | None:
    async with get_session_factory()() as session:
        return (
            await session.execute(
                select(ChannelTarget).where(
                    ChannelTarget.guild_id == guild_id,
                    ChannelTarget.channel_id == channel_id,
                )
            )
        ).scalar_one_or_none()


async def list_channel_targets(
    guild_id: str | None = None, set_by_user_id: int | None = None
) -> list[ChannelTarget]:
    async with get_session_factory()() as session:
        stmt = select(ChannelTarget)
        if guild_id is not None:
            stmt = stmt.where(ChannelTarget.guild_id == guild_id)
        if set_by_user_id is not None:
            stmt = stmt.where(ChannelTarget.set_by_user_id == set_by_user_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def remove_channel_target(guild_id: str, channel_id: str) -> bool:
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(ChannelTarget).where(
                ChannelTarget.guild_id == guild_id,
                ChannelTarget.channel_id == channel_id,
            )
        )
        await session.commit()
        return result.rowcount > 0


async def delete_channel_targets_by_user(set_by_user_id: int) -> int:
    """Delete every channel feed configured by a user (right to erasure)."""
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(ChannelTarget).where(ChannelTarget.set_by_user_id == set_by_user_id)
        )
        await session.commit()
        return result.rowcount


async def purge_channel_sent_history(guild_id: str, channel_id: str) -> int:
    """Delete a channel's dedup/audit history when its feed is removed."""
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(SentMessage).where(
                SentMessage.platform == "discord",
                SentMessage.delivery_kind == DeliveryMethod.channel,
                SentMessage.guild_id == guild_id,
                SentMessage.recipient_id == channel_id,
            )
        )
        await session.commit()
        return result.rowcount or 0
