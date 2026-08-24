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

# Capped exponential backoff for Discord startup (e.g. a temporary 429 IP
# block clears within minutes). Bounded total wait (~25 min) — never an
# indefinite retry loop. Only the lightweight auth probe is retried;
# bot.start() itself runs exactly once per process.
_DISCORD_START_DELAYS = (30, 60, 120, 240, 480, 600)
_MAX_DISCORD_START_DELAY = 600
_DISCORD_API_URL = "https://discord.com/api/v10"


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
    """Wait for Discord auth to succeed (capped backoff), then start once.

    bot.start() must run exactly once per process: it triggers setup_hook,
    which registers cogs and syncs commands. Retrying it wholesale would
    double-register them, so all retrying happens at the cheap probe level.
    """
    token = settings.discord_token
    for attempt, delay in enumerate(_DISCORD_START_DELAYS, start=1):
        status, retry_after = await _probe_discord_auth(token)
        if status == 200:
            await bot.start(token)
            return
        if status == 401:
            logger.error("Discord rejected the bot token; Discord stays down until restart")
            return
        reason = f"HTTP {status}" if status is not None else "network error"
        hint = f" (server says retry after {retry_after}s)" if retry_after else ""
        logger.warning(
            "Discord API not ready (attempt %d/%d): %s%s — retrying in %ds",
            attempt,
            len(_DISCORD_START_DELAYS),
            reason,
            hint,
            delay,
        )
        await asyncio.sleep(min(delay, _MAX_DISCORD_START_DELAY))
    logger.critical(
        "Discord bot gave up after %d startup attempts; Discord stays down "
        "until the process is restarted.",
        len(_DISCORD_START_DELAYS),
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
