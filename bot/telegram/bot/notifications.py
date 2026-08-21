from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import urlparse

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


_VENDOR_ACRONYMS = {"aws": "AWS", "suse": "SUSE"}


def _pretty_vendor(vendor: Any) -> str:
    if not vendor:
        return ""
    try:
        text = str(vendor).strip()
        return _VENDOR_ACRONYMS.get(text.lower(), text.title())
    except Exception:
        return str(vendor)


def _confidence_tier(confidence: Any) -> str | None:
    """Map a 0..1 score to the tier label used by the site's AI flag."""
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return None
    if conf >= 0.8:
        return "High"
    if conf >= 0.5:
        return "Moderate"
    return "Lower"


def _listed_date(post: dict[str, Any]) -> str:
    for key in ("created_at", "published_at"):
        raw = post.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    return ""


def _source_host(post: dict[str, Any], fallback_url: Any) -> str:
    url = post.get("url") or fallback_url
    if not url:
        return ""
    try:
        host = urlparse(str(url)).hostname or ""
    except ValueError:
        return ""
    return host


def _summary_line(vendor: str, discount: Any) -> str:
    """One-line summary, mirroring the site's card summary."""
    if not discount:
        return ""
    if vendor:
        return f"Save {discount} on {vendor} certification exams."
    return f"Save {discount} on certification exams."


def render_post_message(post: dict[str, Any]) -> str:
    """Render a voucher post like the site's opportunity page.

    Layout mirrors the web card/detail view: linked title, a chips row
    (vendor · discount), the summary line, labeled details, the AI assessment
    framed separately ("why it was flagged"), and a source-host meta line.
    """
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

    chips_parts = [vendor, discount and str(discount)]
    chips = " · ".join(p for p in chips_parts if p)
    if chips:
        lines.append(f"<b>{escape(chips)}</b>")

    summary = _summary_line(vendor, discount)
    if summary:
        lines.append("")
        lines.append(escape(summary))

    # Details section (site: Vendor / Type / Regions / Promotion / Source).
    detail_lines: list[str] = []
    promotion_name = str(post.get("promotion_name") or ai.get("promotion_name") or "").strip()
    if promotion_name and promotion_name.lower() not in str(title).lower():
        detail_lines.append(f"Promotion: {escape(promotion_name)}")
    promotion_type = post.get("promotion_type") or ai.get("promotion_type")
    if promotion_type:
        detail_lines.append(f"Type: {escape(str(promotion_type).strip().capitalize())}")
    regions = _join(ai.get("regions"))
    if regions:
        detail_lines.append(f"Regions: {escape(regions)}")
    certifications = _join(ai.get("certifications"))
    if certifications:
        detail_lines.append(f"Certifications: {escape(certifications)}")
    voucher_code = post.get("voucher_code") or ai.get("voucher_code")
    if voucher_code:
        detail_lines.append(f"Code: <code>{escape(str(voucher_code))}</code>")
    if detail_lines:
        lines.append("")
        lines.extend(detail_lines)

    # AI assessment, kept separate from the offer itself (like the site).
    reason = post.get("reason") or ai.get("reason")
    if reason:
        lines.append(f"Why it was flagged: {escape(f'“{reason}”')}")

    meta_parts = []
    host = _source_host(post, url)
    if host:
        meta_parts.append(host)
    listed = _listed_date(post)
    if listed:
        meta_parts.append(f"Listed {listed}")
    author = post.get("author")
    if author:
        meta_parts.append(f"via {author}")
    if meta_parts:
        lines.append("")
        lines.append(escape(" · ".join(meta_parts)))

    tier = _confidence_tier(ai.get("confidence"))
    footer_parts = ["AI"]
    if tier:
        footer_parts.append(f"{tier} confidence")
    footer_parts.append("not a verification of the offer")
    lines.append(escape(" · ".join(footer_parts)))

    if url:
        lines.append("")
        lines.append(f'<a href="{escape(str(url))}">Open the original source</a>')

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
