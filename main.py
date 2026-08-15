from __future__ import annotations

import asyncio
import logging

import uvicorn

from bot.discord.database.connection import ensure_schema
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def run() -> None:
    try:
        await ensure_schema()
        logger.info("Schema ensured")
    except Exception:
        logger.exception("Schema init failed; continuing startup")

    from bot.discord.bot.client import build_bot
    from webhook.server import create_app

    bot = build_bot()
    app = create_app(bot)
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

    # One process, two independent tasks: a webhook failure must not take the
    # Discord bot offline, and vice versa.
    bot_task = asyncio.create_task(_guarded("discord bot", bot.start(settings.discord_token)))
    server_task = asyncio.create_task(_guarded("webhook server", server.serve()))
    await asyncio.gather(bot_task, server_task)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
