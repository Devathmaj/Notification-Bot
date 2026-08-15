from __future__ import annotations

import asyncio
import logging

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
    tasks = [asyncio.create_task(_guarded("webhook server", server.serve()))]
    if settings.has_discord_token:
        tasks.append(
            asyncio.create_task(_guarded("discord bot", bot.start(settings.discord_token)))
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
