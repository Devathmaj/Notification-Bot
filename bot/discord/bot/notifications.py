from __future__ import annotations

import json
from typing import Any

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


def _pretty_vendor(vendor: Any) -> str:
    if not vendor:
        return ""
    try:
        return str(vendor).strip().title()
    except Exception:
        return str(vendor)


def build_post_embed(post: dict[str, Any]) -> discord.Embed:
    """Render a voucher post as a compact notification card."""
    ai = _coerce_ai(post)

    title = post.get("title") or ai.get("promotion_name") or "New notification"
    url = post.get("registration_url") or ai.get("registration_url") or post.get("url") or None
    embed = discord.Embed(title=str(title), url=url)

    vendor = _pretty_vendor(post.get("vendor") or ai.get("vendor"))
    discount = post.get("discount") or ai.get("discount")
    reason = post.get("reason") or ai.get("reason")

    promotion_type = post.get("promotion_type") or ai.get("promotion_type")
    if not discount and "voucher" in str(promotion_type or "").lower():
        discount = "Voucher"

    # Header line: vendor + discount/type
    header_parts = [vendor, discount and str(discount)]
    header = " ".join(p for p in header_parts if p)

    description = ""
    if header:
        description += f"**{header}**\n"
    if reason:
        description += f"{reason}\n"

    # Compact meta as plain lines (matches the notification-card format).
    promotion_name = str(post.get("promotion_name") or ai.get("promotion_name") or "").strip()
    if promotion_name and promotion_name.lower() not in str(title).lower():
        description += f"\n{promotion_name}"

    regions = _join(ai.get("regions"))
    if regions:
        description += f"\n{regions}"

    if promotion_type:
        description += f"\n{promotion_type}"

    end_date = ai.get("end_date")
    if end_date:
        description += f"\n📅 Ends {end_date}"

    author = post.get("author")
    if author:
        description += f"\n👤 {author}"

    embed.description = description.rstrip() or None

    if url and embed.description:
        embed.description = f"{embed.description}\n\n[View Details]({url})"

    # Inline details worth keeping.
    fields: list[tuple[str, str, bool]] = []
    voucher_code = post.get("voucher_code") or ai.get("voucher_code")
    if voucher_code:
        fields.append(("Code", f"`{voucher_code}`", True))
    certifications = _join(ai.get("certifications"))
    if certifications:
        fields.append(("Certifications", certifications, False))
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    confidence = ai.get("confidence")
    footer = None
    if vendor:
        footer = vendor
    if confidence is not None:
        try:
            conf = float(confidence)
        except (ValueError, TypeError):
            conf = None
        if conf is not None:
            badge = f"Confidence {conf:.2f}"
            footer = f"{footer} · {badge}" if footer else badge
    if footer:
        embed.set_footer(text=footer)

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
