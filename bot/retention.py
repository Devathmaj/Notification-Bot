from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, cast, delete, select

from bot.discord.database.connection import get_session_factory
from bot.discord.database.models import DeliveryMethod, Preference, SentMessage
from bot.telegram.database.models import TelegramUser

logger = logging.getLogger("retention")

DEFAULT_RETENTION_DAYS = 7


def _expired_dm_ids(cutoff: datetime, platform: str) -> Any:
    """Select DM rows older than ``cutoff`` whose subscription no longer exists.

    ``/delete`` (Discord) removes the user's preferences row and ``/stop``
    (Telegram) removes the telegram_users row, so a missing subscriber row means
    the user asked to be erased. Their old delivery records are then fair game.
    """
    if platform == "discord":
        subscriber_pk = Preference.user_id
    else:
        subscriber_pk = TelegramUser.chat_id

    return (
        select(SentMessage.id)
        .where(
            SentMessage.platform == platform,
            SentMessage.delivery_kind == DeliveryMethod.dm,
            SentMessage.created_at < cutoff,
        )
        .where(
            ~(
                select(subscriber_pk)
                .where(subscriber_pk == cast(SentMessage.recipient_id, BigInteger))
            ).exists()
        )
    )


async def purge_expired_sent_messages(after_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete sent_messages for users who removed their subscription a week ago.

    DM delivery rows store the recipient snowflake/chat id in ``recipient_id``;
    once the matching preferences/telegram_users row is gone (via /delete or
    /stop) and the delivery is older than ``after_days``, the audit rows are
    purged. Channel/group rows are shared feeds, not user data, so they are left.
    """
    cutoff = datetime.now(UTC) - timedelta(days=after_days)
    total = 0
    async with get_session_factory()() as session:
        for platform in ("discord", "telegram"):
            result = await session.execute(
                delete(SentMessage).where(SentMessage.id.in_(_expired_dm_ids(cutoff, platform)))
            )
            total += result.rowcount or 0
        await session.commit()
    return total
