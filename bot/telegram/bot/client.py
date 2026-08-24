from __future__ import annotations

import logging

from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)
from telegram.ext import Application, ApplicationBuilder

from bot.telegram.bot.commands import register_handlers
from config import settings

logger = logging.getLogger("telegram.bot")

_PRIVATE_COMMANDS = [
    BotCommand("start", "Subscribe to notifications in this chat"),
    BotCommand("latest", "Show the newest voucher alert"),
    BotCommand("top", "Show recent alerts, e.g. /top 5"),
    BotCommand("about", "Learn what this bot is about"),
    BotCommand("help", "How to use this bot"),
    BotCommand("stop", "Unsubscribe and delete your data"),
]

_GROUP_COMMANDS = [
    BotCommand("latest", "Show the newest voucher alert"),
    BotCommand("top", "Show recent alerts, e.g. /top 5"),
    BotCommand("about", "Learn what this bot is about"),
    BotCommand("help", "How to use this bot"),
]


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

    # Surface the command menu in Telegram's UI. /start and /stop are private
    # chats only (handler filters), so they are not advertised in groups.
    try:
        await application.bot.set_my_commands(
            _PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats()
        )
        await application.bot.set_my_commands(
            _GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats()
        )
    except Exception:
        logger.warning("Could not register the Telegram command menu", exc_info=True)


async def stop_application(application: Application) -> None:
    await application.stop()
    await application.shutdown()
