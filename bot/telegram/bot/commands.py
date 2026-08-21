from __future__ import annotations

import asyncio
import logging
from functools import wraps

from telegram import Update
from telegram.ext import ChatMemberHandler, CommandHandler, ContextTypes
from telegram.ext.filters import ChatType

from bot.discord.database.posts import fetch_latest_posts
from bot.rate_limit import RATE_LIMIT_TEXT, WindowRateLimiter, parse_rate
from bot.telegram.bot.logging_utils import redact_chat_id
from bot.telegram.bot.notifications import render_post_message
from bot.telegram.database.groups import (
    delete_telegram_group,
    purge_group_sent_history,
    upsert_telegram_group,
)
from bot.telegram.database.users import delete_telegram_user, upsert_telegram_user
from config import settings

logger = logging.getLogger("telegram.bot.commands")

MAX_TOP = 100
_PACE_SECONDS = 0.35

telegram_limiter = WindowRateLimiter(*parse_rate(settings.telegram_command_rate))


def _rate_limited(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        key = (
            update.effective_user.id
            if update.effective_user is not None
            else update.effective_chat.id
        )
        if not telegram_limiter.allow(f"telegram:{key}"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=RATE_LIMIT_TEXT
            )
            return
        return await handler(update, context)

    return wrapper

_ADDED_STATUSES = {"member", "administrator", "restricted", "creator"}
_LEFT_STATUSES = {"left", "kicked"}

HELP_TEXT = (
    "<b>Notification Bot</b>\n\n"
    "I watch for new voucher alerts and deliver them to you directly in this "
    "chat or to any group I am added to.\n\n"
    "<b>Commands</b>\n"
    "• /start — subscribe to notifications in this private chat\n"
    "• /latest — show the newest notification with its full details (vendor, "
    "discount, voucher code, certifications, expiry)\n"
    "• /top &lt;n&gt; — show the n most recent notifications, newest first "
    "(1–100)\n"
    "• /about — learn what this bot is about and find useful links\n"
    "• /stop — unsubscribe and delete your stored data\n"
    "• /help — show this message\n\n"
    "<b>Behaviour</b>\n"
    "• If I'm in a group chat, new alerts are posted there automatically.\n"
    "• In a private chat, new alerts are sent to you after /start.\n"
    "• Commands work in private chats and groups.\n"
    "• Unsubscribing does not delete earlier messages you received.\n\n"
    "<b>Links</b>\n"
    "• Privacy policy: <a href=\"https://voucherbot-preview.pages.dev/#telegram/privacy\">"
    "voucherbot-preview.pages.dev/#telegram/privacy</a>\n"
    "• Terms of service: <a href=\"https://voucherbot-preview.pages.dev/#telegram/terms\">"
    "voucherbot-preview.pages.dev/#telegram/terms</a>\n"
    "• Disclaimer: <a href=\"https://voucherbot-preview.pages.dev/#telegram/disclaimer\">"
    "voucherbot-preview.pages.dev/#telegram/disclaimer</a>\n"
)

ABOUT_TEXT = (
    "<b>VoucherBot Notifications</b>\n\n"
    "I'm the notification service for <b>VoucherBot</b> — an open-source aggregator "
    "that continuously monitors vendor sites, training providers, and community "
    "sources for certification discounts, free exam vouchers, beta exams, and "
    "training promotions. Automated (AI-assisted) analysis reviews each finding and "
    "flags likely offers — flagged items are published with their source and dates, "
    "never as a verification of the offer. This bot delivers every new listing "
    "straight to you, the moment it is discovered.\n\n"
    "<b>Website</b>\n"
    "Browse everything VoucherBot has collected, see how discovery works, and read "
    "the full notification setup guide:\n"
    "<b><a href=\"https://voucherbot-preview.pages.dev/\">voucherbot-preview.pages.dev</a></b>\n\n"
    "<b>What I do here</b>\n"
    "• Push each new listing to this private chat (after /start) and to any group "
    "I'm added to.\n"
    "• Answer on-demand queries: /latest for the newest post, /top &lt;n&gt; for the "
    "recent ones.\n"
    "• Deliver each alert exactly once — retries are deduplicated.\n"
    "• Stay privacy-first: /stop erases your subscription data anytime.\n\n"
    "<b>Source code</b>\n"
    "The collection pipeline is open source: "
    "<a href=\"https://github.com/Devathmaj/VoucherBot\">github.com/Devathmaj/VoucherBot</a>\n\n"
    "<b>Commands</b>\n"
    "Use /help to see all available commands and what they do."
)


async def _reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str | None = None
) -> None:
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode=parse_mode
    )


async def _send_paced(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML")
    await asyncio.sleep(_PACE_SECONDS)


@_rate_limited
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    await upsert_telegram_user(
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    first = user.first_name or "there"
    await context.bot.send_message(
        chat_id=chat.id,
        text=(
            f"Hi {first}! You are now subscribed to notifications here.\n\n"
            "Use /latest for the newest post, /top <n> for recent ones, "
            "and /help for more information."
        ),
    )


@_rate_limited
async def handle_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    posts = await fetch_latest_posts(limit=1)
    if not posts:
        await _reply(update, context, "No notifications yet.")
        return
    await _reply(update, context, render_post_message(posts[0]), parse_mode="HTML")


@_rate_limited
async def handle_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or []).strip()
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= MAX_TOP:
        await _reply(update, context, f"Please pick a number between 1 and {MAX_TOP}.")
        return
    posts = await fetch_latest_posts(limit=n)
    if not posts:
        await _reply(update, context, "No notifications yet.")
        return
    for post in posts:
        await _send_paced(update, context, render_post_message(post))


@_rate_limited
async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, context, HELP_TEXT, parse_mode="HTML")


@_rate_limited
async def handle_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, context, ABOUT_TEXT, parse_mode="HTML")


@_rate_limited
async def handle_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    deleted = await delete_telegram_user(chat.id)
    if deleted:
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "You've been unsubscribed and your data has been deleted. "
                "Send /start anytime to resubscribe."
            ),
        )
    else:
        await context.bot.send_message(
            chat_id=chat.id,
            text="You weren't subscribed, so there was nothing to delete. "
            "Send /start to subscribe.",
        )


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = update.my_chat_member
    if member is None:
        return
    chat = member.chat
    status = member.new_chat_member.status
    if status in _ADDED_STATUSES:
        await upsert_telegram_group(chat_id=chat.id, title=chat.title, chat_type=chat.type)
        logger.info("Bot added to chat %s (%s)", redact_chat_id(chat.id), chat.type)
    elif status in _LEFT_STATUSES:
        await delete_telegram_group(chat.id)
        await purge_group_sent_history(chat.id)
        logger.info("Bot removed from chat %s", redact_chat_id(chat.id))


def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", handle_start, filters=ChatType.PRIVATE))
    application.add_handler(CommandHandler("stop", handle_stop, filters=ChatType.PRIVATE))
    application.add_handler(CommandHandler("latest", handle_latest))
    application.add_handler(CommandHandler("top", handle_top))
    application.add_handler(CommandHandler("about", handle_about))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(
        ChatMemberHandler(
            handle_my_chat_member, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER
        )
    )
