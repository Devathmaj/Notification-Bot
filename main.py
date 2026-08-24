from __future__ import annotations

import asyncio
import logging

import discord
import uvicorn

from bot.discord.database.connection import ensure_schema

# Import early so the Telegram tables are registered on the shared metadata
# before ensure_schema() runs (they are created by Base.metadata.create_all).
from bot.telegram.database import models as _telegram_models  # noqa: F401
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

_RETENTION_INTERVAL_SECONDS = 6 * 60 * 60

# Discord startup retry policy. When a probe gets 429'd, Discord's own
# Retry-After is authoritative and is followed as-is (+ small buffer, sanity-
# clamped). Without a hint we fall back to a capped exponential schedule.
# Everything stays bounded: max attempts AND a total wait budget (~65 min,
# sized so any single server hint up to 1h fits), so a retry can never delay
# startup indefinitely. bot.start() itself runs exactly once per process;
# only the lightweight auth probe retries.
_DISCORD_FALLBACK_DELAYS = (30, 60, 120, 240, 480, 600)
_DISCORD_MAX_FALLBACK_DELAY = 600
_DISCORD_MAX_HINT_SECONDS = 3600
_DISCORD_RETRY_BUFFER_SECONDS = 5
_DISCORD_MAX_ATTEMPTS = 6
_DISCORD_MAX_TOTAL_WAIT = 3900
_DISCORD_API_URL = "https://discord.com/api/v10"

_sleep = asyncio.sleep  # indirect so tests can observe waits


async def _probe_discord_auth(token: str) -> tuple[int | None, int | None]:
    """Single Discord auth probe.

    Returns (HTTP status, server-provided Retry-After in seconds if sent).
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
                return resp.status, retry_after
    except (aiohttp.ClientError, OSError, TimeoutError):
        return None, None


async def _start_discord_when_ready(bot: discord.Client) -> None:
    """Wait for Discord auth to succeed, then start the bot once.

    Retry timing follows Discord's own Retry-After when provided (plus a
    small buffer); otherwise falls back to capped exponential backoff.
    Bounded by _DISCORD_MAX_ATTEMPTS and _DISCORD_MAX_TOTAL_WAIT so startup
    can never be delayed indefinitely. bot.start() must run exactly once per
    process: it triggers setup_hook, which registers cogs and syncs commands.
    """
    token = settings.discord_token
    waited = 0
    for attempt in range(1, _DISCORD_MAX_ATTEMPTS + 1):
        status, hint = await _probe_discord_auth(token)
        if status == 200:
            await bot.start(token)
            return
        if status == 401:
            logger.error("Discord rejected the bot token; Discord stays down until restart")
            return

        reason = f"HTTP {status}" if status is not None else "network error"
        if attempt == _DISCORD_MAX_ATTEMPTS:
            break

        if hint is not None:
            wait = min(max(hint, 1) + _DISCORD_RETRY_BUFFER_SECONDS, _DISCORD_MAX_HINT_SECONDS)
            basis = f"following Discord's retry-after ({wait}s)"
        else:
            fallback = _DISCORD_FALLBACK_DELAYS[min(attempt, len(_DISCORD_FALLBACK_DELAYS)) - 1]
            wait = min(fallback, _DISCORD_MAX_FALLBACK_DELAY)
            basis = f"no retry hint — backing off ({wait}s)"

        if waited + wait > _DISCORD_MAX_TOTAL_WAIT:
            logger.critical(
                "Discord still unavailable after %d attempts (waited %ds); next wait would "
                "exceed the %ds startup budget. Discord stays down until restart.",
                attempt,
                waited,
                _DISCORD_MAX_TOTAL_WAIT,
            )
            return

        logger.warning(
            "Discord API not ready (attempt %d/%d): %s — %s",
            attempt,
            _DISCORD_MAX_ATTEMPTS,
            reason,
            basis,
        )
        await _sleep(wait)
        waited += wait
    logger.critical(
        "Discord bot gave up after %d attempts (waited %ds total); Discord stays down "
        "until the process is restarted.",
        _DISCORD_MAX_ATTEMPTS,
        waited,
    )


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
