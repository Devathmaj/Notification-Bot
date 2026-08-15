from __future__ import annotations

import asyncio
import json
import logging
from html import escape
from typing import Any

from sqlalchemy import select

from bot.discord.database.connection import get_session_factory
from bot.discord.database.models import DeliveryMethod, SentMessage
from bot.telegram.bot.logging_utils import redact_chat_id
from bot.telegram.database.groups import list_active_groups
from bot.telegram.database.users import list_telegram_users

logger = logging.getLogger("telegram.bot.notifications")

_PACE_SECONDS = 0.5


def _coerce_ai(post: dict[str, Any]) -> dict[str, Any]:
    ai = post.get("ai_result") or {}
    if isinstance(ai, str):
        try:
            ai = json.loads(ai)
        except (json.JSONDecodeError, TypeError):
            ai = {}
    return ai if isinstance(ai, dict) else {}


def _join(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    return str(value)


def _pretty_vendor(vendor: Any) -> str:
    if not vendor:
        return ""
    try:
        return str(vendor).strip().title()
    except Exception:
        return str(vendor)


def render_post_message(post: dict[str, Any]) -> str:
    """Render a voucher post as an HTML message (Telegram has no embeds)."""
    ai = _coerce_ai(post)

    title = post.get("title") or ai.get("promotion_name") or "New notification"
    url = post.get("registration_url") or ai.get("registration_url") or post.get("url") or None

    lines: list[str] = []
    if url:
        lines.append(f'<b><a href="{escape(str(url))}">{escape(str(title))}</a></b>')
    else:
        lines.append(f"<b>{escape(str(title))}</b>")

    vendor = _pretty_vendor(post.get("vendor") or ai.get("vendor"))
    discount = post.get("discount") or ai.get("discount")
    reason = post.get("reason") or ai.get("reason")
    promotion_type = post.get("promotion_type") or ai.get("promotion_type")
    if not discount and "voucher" in str(promotion_type or "").lower():
        discount = "Voucher"

    header_parts = [vendor, discount and str(discount)]
    header = " ".join(p for p in header_parts if p)
    if header:
        lines.append(f"<b>{escape(header)}</b>")
    if reason:
        lines.append(escape(str(reason)))

    promotion_name = str(post.get("promotion_name") or ai.get("promotion_name") or "").strip()
    if promotion_name and promotion_name.lower() not in str(title).lower():
        lines.append(escape(promotion_name))

    regions = _join(ai.get("regions"))
    if regions:
        lines.append(escape(regions))
    if promotion_type:
        lines.append(escape(str(promotion_type)))
    end_date = ai.get("end_date")
    if end_date:
        lines.append(f"📅 Ends {escape(str(end_date))}")
    author = post.get("author")
    if author:
        lines.append(f"👤 {escape(str(author))}")

    voucher_code = post.get("voucher_code") or ai.get("voucher_code")
    if voucher_code:
        lines.append(f"<code>{escape(str(voucher_code))}</code>")
    certifications = _join(ai.get("certifications"))
    if certifications:
        lines.append(f"⚖️ {escape(certifications)}")

    if url:
        lines.append(f'<a href="{escape(str(url))}">View Details</a>')

    return "\n".join(lines)


async def _send_message(bot: Any, chat_id: int, text: str) -> int | None:
    try:
        message = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return message.message_id
    except Exception:
        logger.debug("Telegram send to chat %s failed", redact_chat_id(chat_id), exc_info=True)
        return None


async def notify_for_post(application: Any, post: dict[str, Any]) -> int:
    """Deliver a post to every subscribed private chat and active group.

    Dedup is per (platform, kind, post, recipient), where recipient is a chat id
    (str), so webhook retries never double-send.
    """
    text = render_post_message(post)
    post_id = str(post.get("id") or post.get("post_id"))

    users = await list_telegram_users()
    groups = await list_active_groups()
    if not users and not groups:
        return 0

    async with get_session_factory()() as session:
        result = await session.execute(
            select(SentMessage.delivery_kind, SentMessage.recipient_id).where(
                SentMessage.platform == "telegram", SentMessage.post_id == post_id
            )
        )
        already = {(kind, recipient) for kind, recipient in result.all()}

    sent = 0
    async with get_session_factory()() as session:
        for user in users:
            chat_id = user.chat_id
            if (DeliveryMethod.dm, str(chat_id)) in already:
                continue
            message_id = await _send_message(application.bot, chat_id, text)
            if message_id is not None:
                session.add(
                    SentMessage(
                        platform="telegram",
                        delivery_kind=DeliveryMethod.dm,
                        post_id=post_id,
                        recipient_id=str(chat_id),
                        telegram_message_id=str(message_id),
                    )
                )
                sent += 1
                await asyncio.sleep(_PACE_SECONDS)

        for group in groups:
            chat_id = group.chat_id
            if (DeliveryMethod.channel, str(chat_id)) in already:
                continue
            message_id = await _send_message(application.bot, chat_id, text)
            if message_id is not None:
                session.add(
                    SentMessage(
                        platform="telegram",
                        delivery_kind=DeliveryMethod.channel,
                        post_id=post_id,
                        recipient_id=str(chat_id),
                        telegram_message_id=str(message_id),
                    )
                )
                sent += 1
                await asyncio.sleep(_PACE_SECONDS)
        await session.commit()

    return sent
