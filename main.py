from __future__ import annotations

import asyncio
import logging

import discord
import uvicorn

from bot.discord.database.connection import ensure_schema
from bot.logging_utils import setup_logging

# Import early so the Telegram tables are registered on the shared metadata
# before ensure_schema() runs (they are created by Base.metadata.create_all).
from bot.telegram.database import models as _telegram_models  # noqa: F401
from config import settings

setup_logging(logging.INFO)
logger = logging.getLogger("main")

_RETENTION_INTERVAL_SECONDS = 6 * 60 * 60

# Discord startup retry policy. When a check gets 429'd, Discord's own
# Retry-After is authoritative: we follow it (+ small buffer, sanity-clamped)
# for as long as it takes — the check runs as a background task, so nothing
# else is delayed and each retry is one tiny request timed by Discord itself.
# Without a hint we fall back to a capped exponential schedule. The only
# permanent failure is a rejected token (401), which stops immediately.
# bot.start() itself runs exactly once per process; only the check retries.
_DISCORD_FALLBACK_DELAYS = (30, 60, 120, 240, 480, 600)
_DISCORD_MAX_FALLBACK_DELAY = 600
_DISCORD_MAX_HINT_SECONDS = 3600
_DISCORD_RETRY_BUFFER_SECONDS = 5
_DISCORD_API_URL = "https://discord.com/api/v10"

_sleep = asyncio.sleep  # indirect so tests can observe waits


async def _check_discord_api(token: str) -> tuple[int | None, int | None, dict | None]:
    """Check Discord API availability.

    Returns (HTTP status, server-provided Retry-After in seconds if sent, rate limit headers).
    Status is None on network errors.
    """
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_DISCORD_API_URL}/users/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                retry_after: int | None = None
                raw = resp.headers.get("Retry-After")
                if raw:
                    try:
                        retry_after = max(0, int(float(raw)))
                    except ValueError:
                        retry_after = None

                # Capture rate limit headers for diagnostics
                rate_limit_headers = {
                    "retry_after": retry_after,
                    "x_ratelimit_global": resp.headers.get("X-RateLimit-Global"),
                    "x_ratelimit_remaining": resp.headers.get("X-RateLimit-Remaining"),
                    "x_ratelimit_reset_after": resp.headers.get("X-RateLimit-Reset-After"),
                }

                # Read response body for diagnostics (Discord often includes useful info in 429 responses)
                body = None
                try:
                    body = await resp.json()
                except Exception:
                    body = await resp.text()

                return resp.status, retry_after, rate_limit_headers
    except (aiohttp.ClientError, OSError, TimeoutError) as e:
        logger.debug("Discord API check network error: %s", e)
        return None, None, None


async def _start_discord_when_ready(bot: discord.Client) -> None:
    """Wait for Discord API to be available, then start the bot once.

    Retry timing follows Discord's own Retry-After when provided (plus a
    small buffer) for as long as it takes; without a hint it falls back to
    capped exponential backoff. Only a rejected token (401) stops retrying,
    since no amount of waiting fixes an invalid token. bot.start() must run
    exactly once per process: it triggers setup_hook, which registers cogs
    and syncs commands.
    """
    token = settings.discord_token
    attempt = 0
    while True:
        attempt += 1
        status, retry_after, rate_limit_headers = await _check_discord_api(token)
        if status == 200:
            logger.info("Discord API check passed, starting bot")
            await bot.start(token)
            return
        if status == 401:
            logger.error("Discord rejected the bot token; Discord bot stays down until restart")
            return

        # Build diagnostic log message with all available rate limit info
        reason = f"HTTP {status}" if status is not None else "network error"
        rate_limit_info = ""
        if rate_limit_headers:
            parts = []
            if rate_limit_headers.get("x_ratelimit_global") is not None:
                parts.append(f"global={rate_limit_headers['x_ratelimit_global']}")
            if rate_limit_headers.get("x_ratelimit_remaining") is not None:
                parts.append(f"remaining={rate_limit_headers['x_ratelimit_remaining']}")
            if rate_limit_headers.get("x_ratelimit_reset_after") is not None:
                parts.append(f"reset_after={rate_limit_headers['x_ratelimit_reset_after']}s")
            if parts:
                rate_limit_info = f" — rate limits: {', '.join(parts)}"

        if retry_after is not None:
            wait = min(max(retry_after, 1) + _DISCORD_RETRY_BUFFER_SECONDS, _DISCORD_MAX_HINT_SECONDS)
            basis = f"following Discord's retry-after ({wait}s)"
        else:
            fallback = _DISCORD_FALLBACK_DELAYS[min(attempt, len(_DISCORD_FALLBACK_DELAYS)) - 1]
            wait = min(fallback, _DISCORD_MAX_FALLBACK_DELAY)
            basis = f"no retry hint — backing off ({wait}s)"

        logger.warning(
            "Discord API not ready (attempt %d): %s%s — %s",
            attempt,
            reason,
            rate_limit_info,
            basis,
        )
        await _sleep(wait)


async def _retention_sweep() -> None:
    from bot.retention import purge_expired_sent_messages

    while True:
        try:
            removed = await purge_expired_sent_messages()
            logger.info("Retention sweep removed %s stale sent messages", removed)
        except Exception:
            logger.exception("Retention sweep failed; retrying later")
        await asyncio.sleep(_RETENTION_INTERVAL_SECONDS)


async def _telegram_main(application) -> None:
    from bot.telegram.bot.client import start_application, stop_application

    try:
        await start_application(application)
        await asyncio.Event().wait()
    finally:
        await stop_application(application)


async def run() -> None:
    try:
        await ensure_schema()
        logger.info("Schema ensured")
    except Exception:
        logger.exception("Schema init failed; continuing startup")

    from bot.discord.bot.client import build_bot
    from bot.telegram.bot.client import build_application
    from webhook.server import create_app

    telegram_application = build_application() if settings.has_telegram_token else None
    bot = build_bot()
    app = create_app(bot, telegram_application=telegram_application)
    config = uvicorn.Config(
        app, host=settings.webhook_host, port=settings.webhook_port, log_level="info"
    )
    server = uvicorn.Server(config)
    logger.info(
        "Webhook server listening on http://%s:%s", settings.webhook_host, settings.webhook_port
    )

    async def _guarded(name: str, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s stopped unexpectedly, continuing", name)

    # One process, independent tasks: a webhook failure must not take the
    # Discord or Telegram bots offline, and vice versa.
    tasks = [
        asyncio.create_task(_guarded("webhook server", server.serve())),
        asyncio.create_task(_guarded("retention sweep", _retention_sweep())),
    ]
    if settings.has_discord_token:
        tasks.append(
            asyncio.create_task(_guarded("discord bot", _start_discord_when_ready(bot)))
        )
    if telegram_application is not None:
        tasks.append(
            asyncio.create_task(_guarded("telegram bot", _telegram_main(telegram_application)))
        )
    await asyncio.gather(*tasks)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
