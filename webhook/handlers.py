from __future__ import annotations

from typing import Any

import discord

from bot.discord.bot.notifications import notify_for_post as notify_discord
from bot.telegram.bot.notifications import notify_for_post as notify_telegram

EXPECTED_EVENT = "voucher_alert"


class InvalidEvent(ValueError):
    pass


def build_post(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a voucher_alert event to the post dict the notifier expects.

    ``post`` is the announcement URL and doubles as the idempotency key used
    for dedup, so webhook retries never double-send. AI-extracted extras are
    folded into ``ai_result`` for the embed renderer.
    """
    return {
        "id": payload.get("post"),
        "title": payload.get("title"),
        "url": payload.get("post"),
        "registration_url": payload.get("claim_url"),
        "vendor": payload.get("vendor"),
        "promotion_name": payload.get("promotion_name"),
        "promotion_type": payload.get("promotion_type"),
        "voucher_code": payload.get("voucher_code"),
        "discount": payload.get("discount"),
        "reason": payload.get("reason"),
        "created_at": payload.get("sent_at"),
        "ai_result": {
            "confidence": payload.get("confidence"),
            "certifications": payload.get("certifications"),
            "regions": payload.get("regions"),
        },
    }


def validate_event(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("event") != EXPECTED_EVENT:
        raise InvalidEvent(f"Only {EXPECTED_EVENT} events are handled")
    if not payload.get("title"):
        raise InvalidEvent("Missing title")
    if not payload.get("post"):
        raise InvalidEvent("Missing post")
    return build_post(payload)


async def handle_event(
    payload: dict[str, Any],
    client: discord.Client | None = None,
    telegram_application: Any | None = None,
) -> int:
    """Process a voucher alert. Returns the number of notifications delivered.

    Delivers to whichever platforms have a client wired in. Per-recipient dedup
    lives in the platform notifiers, so webhook retries never double-send.
    """
    post = validate_event(payload)
    total = 0
    if client is not None:
        total += await notify_discord(client, post)
    if telegram_application is not None:
        total += await notify_telegram(telegram_application, post)
    return total
