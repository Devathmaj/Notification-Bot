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
# indefinite retry loop.
_DISCORD_START_DELAYS = (30, 60, 120, 240, 480, 600)
_MAX_DISCORD_START_DELAY = 600


async def _start_discord_with_retries(bot: discord.Client) -> None:
    """Start the Discord bot, retrying transient startup failures.

    Transient errors (rate limits, network, dropped connections) are retried
    with the capped schedule above; a rejected token is permanent and fails
    immediately. After the final attempt the task gives up until the process
    is restarted — other modules keep running either way.
    """
    for attempt, delay in enumerate(_DISCORD_START_DELAYS, start=1):
        try:
            await bot.start(settings.discord_token)
            return
        except asyncio.CancelledError:
            raise
        except discord.LoginFailure:
            logger.error("Discord rejected the bot token; not retrying")
            return
        except (discord.HTTPException, discord.ConnectionClosed, OSError, TimeoutError) as exc:
            retry_hint = getattr(exc, "retry_after", None)
            logger.warning(
                "Discord startup failed (attempt %d/%d)%s — retrying in %ds",
                attempt,
                len(_DISCORD_START_DELAYS),
                f" (server hint: retry after {int(retry_hint)}s)" if retry_hint else "",
                delay,
                exc_info=True,
            )
            if not bot.is_closed():
                try:
                    await bot.close()
                except Exception:
                    logger.debug("Cleanup after failed Discord start raised", exc_info=True)
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
            asyncio.create_task(_guarded("discord bot", _start_discord_with_retries(bot)))
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
