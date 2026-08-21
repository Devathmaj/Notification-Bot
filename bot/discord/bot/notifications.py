from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import discord
from sqlalchemy import select

from bot.discord.database.channel_targets import list_channel_targets
from bot.discord.database.connection import get_session_factory
from bot.discord.database.models import DeliveryMethod, SentMessage
from bot.discord.database.preferences import list_preferences

_MENTION_CONTENT = {
    "here": "@here",
    "everyone": "@everyone",
}


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


def build_post_embed(post: dict[str, Any]) -> discord.Embed:
    """Render a voucher post like the site's opportunity page.

    Layout mirrors the web card/detail view: a chips row (vendor · discount)
    above the linked title, the summary line, labeled details as fields, the
    AI assessment framed separately ("why it was flagged"), and a source-host
    meta line.
    """
    ai = _coerce_ai(post)

    title = post.get("title") or ai.get("promotion_name") or "New notification"
    url = post.get("registration_url") or ai.get("registration_url") or post.get("url") or None
    embed = discord.Embed(title=str(title), url=url)

    vendor = _pretty_vendor(post.get("vendor") or ai.get("vendor"))
    discount = post.get("discount") or ai.get("discount")
    reason = post.get("reason") or ai.get("reason")

    # Chips row (site: vendor chip · discount chip) sits above the title.
    chips_parts = [vendor, discount and str(discount)]
    chips = " · ".join(p for p in chips_parts if p)
    if chips:
        embed.set_author(name=chips)

    # Summary + source meta line.
    description = _summary_line(vendor, discount)
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
        description += f"\n\n{' · '.join(meta_parts)}" if description else "\n".join(meta_parts)
    embed.description = description.rstrip() or None

    # Details section (site: Vendor / Type / Regions / Promotion / Source).
    promotion_name = str(post.get("promotion_name") or ai.get("promotion_name") or "").strip()
    fields: list[tuple[str, str, bool]] = []
    if promotion_name and promotion_name.lower() not in str(title).lower():
        fields.append(("Promotion", promotion_name, True))
    promotion_type = post.get("promotion_type") or ai.get("promotion_type")
    if promotion_type:
        fields.append(("Type", str(promotion_type).strip().capitalize(), True))
    regions = _join(ai.get("regions"))
    if regions:
        fields.append(("Regions", regions, True))
    certifications = _join(ai.get("certifications"))
    if certifications:
        fields.append(("Certifications", certifications, False))
    voucher_code = post.get("voucher_code") or ai.get("voucher_code")
    if voucher_code:
        fields.append(("Code", f"`{voucher_code}`", True))

    # AI assessment, kept separate from the offer itself (like the site).
    if reason:
        fields.append(("Why it was flagged", f"“{reason}”", False))
    for name, value, inline in fields:
        embed.add_field(name=name, value=value, inline=inline)

    tier = _confidence_tier(ai.get("confidence"))
    footer_parts = ["AI"]
    if tier:
        footer_parts.append(f"{tier} confidence")
    footer_parts.append("not a verification of the offer")
    embed.set_footer(text=" · ".join(footer_parts))

    return embed


async def _send_dm(bot: discord.Client, user_id: int, embed: discord.Embed) -> int | None:
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.NotFound:
            return None
    try:
        message = await user.send(embed=embed)
        return message.id
    except (discord.Forbidden, discord.HTTPException):
        return None


async def _send_channel(
    client: discord.Client,
    guild_id: str,
    channel_id: str,
    embed: discord.Embed,
    content: str | None = None,
) -> int | None:
    guild = client.get_guild(int(guild_id))
    if guild is None:
        return None
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await guild.fetch_channel(int(channel_id))
        except discord.NotFound:
            return None
    if not isinstance(channel, discord.TextChannel):
        return None
    try:
        message = await channel.send(content=content, embed=embed)
        return message.id
    except (discord.Forbidden, discord.HTTPException):
        return None


_MENTION_CONTENT = {
    "here": "@here",
    "everyone": "@everyone",
}


async def notify_for_post(client: discord.Client, post: dict[str, Any]) -> int:
    """Deliver a post to every DM subscription and every channel feed.

    Dedup is per (platform, kind, post_id, recipient), where the recipient is a
    user snowflake for DMs and a channel snowflake for feeds; each channel feed
    therefore goes out exactly once per post regardless of how many users there
    are trying to configure the same channel.
    """
    embed = build_post_embed(post)
    post_id = str(post.get("id") or post.get("post_id"))

    preferences = await list_preferences()
    targets = await list_channel_targets()
    if not preferences and not targets:
        return 0

    already: set[tuple[str, str]] = set()
    async with get_session_factory()() as session:
        result = await session.execute(
            select(SentMessage.delivery_kind, SentMessage.recipient_id).where(
                SentMessage.platform == "discord", SentMessage.post_id == post_id
            )
        )
        already = {(kind, recipient) for kind, recipient in result.all()}

    sent = 0
    async with get_session_factory()() as session:
        for pref in preferences:
            if not pref.dm_enabled:
                continue
            if (DeliveryMethod.dm, str(pref.user_id)) in already:
                continue
            message_id = await _send_dm(client, pref.user_id, embed)
            if message_id is not None:
                session.add(
                    SentMessage(
                        platform="discord",
                        delivery_kind=DeliveryMethod.dm,
                        post_id=post_id,
                        recipient_id=str(pref.user_id),
                        discord_message_id=str(message_id),
                        preference_id=pref.user_id,
                    )
                )
                sent += 1

        for target in targets:
            if (DeliveryMethod.channel, target.channel_id) in already:
                continue
            content = _MENTION_CONTENT.get(target.mention)
            message_id = await _send_channel(
                client, target.guild_id, target.channel_id, embed, content=content
            )
            if message_id is not None:
                session.add(
                    SentMessage(
                        platform="discord",
                        delivery_kind=DeliveryMethod.channel,
                        post_id=post_id,
                        recipient_id=target.channel_id,
                        guild_id=target.guild_id,
                        discord_message_id=str(message_id),
                    )
                )
                sent += 1
        await session.commit()

    return sent
