from __future__ import annotations

import logging

from telegram.ext import Application, ApplicationBuilder

from bot.telegram.bot.commands import register_handlers
from config import settings

logger = logging.getLogger("telegram.bot")


def build_application(
    token: str | None = None, base_url: str | None = None
) -> Application:
    builder = (
        ApplicationBuilder()
        .token(token or settings.telegram_http_api_token)
        .concurrent_updates(True)
        .read_timeout(30)
        .write_timeout(30)
    )
    base = base_url or settings.telegram_http_api_base_url
    if base:
        builder = builder.base_url(base)
    application = builder.build()
    register_handlers(application)
    return application


async def start_application(application: Application) -> None:
    """Initialize the app and register the Telegram webhook (webhook mode only)."""
    await application.initialize()
    await application.start()
    if not settings.telegram_webhook_url:
        logger.warning(
            "TELEGRAM_WEBHOOK_URL not set; the bot will not receive updates. "
            "Set it to https://<host>/telegram/webhook and restart."
        )
        return
    kwargs = {"url": settings.telegram_webhook_url, "drop_pending_updates": True}
    if settings.telegram_webhook_secret:
        kwargs["secret_token"] = settings.telegram_webhook_secret
    await application.bot.set_webhook(**kwargs)
    logger.info("Telegram webhook registered at %s", settings.telegram_webhook_url)


async def stop_application(application: Application) -> None:
    await application.stop()
    await application.shutdown()
