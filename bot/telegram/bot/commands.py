from __future__ import annotations

import asyncio
import logging
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
)
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

MAIN_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("/latest", callback_data="latest"),
            InlineKeyboardButton("/help", callback_data="help"),
        ],
        [
            InlineKeyboardButton("/about", callback_data="about"),
            InlineKeyboardButton("/donate", callback_data="donate"),
        ],
    ]
)


def _log_command(update: Update, command_name: str) -> None:
    """Log a command invocation with user and chat info."""
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id if user else "unknown"
    chat_id = redact_chat_id(chat.id) if chat else "unknown"
    chat_type = chat.type if chat else "unknown"
    logger.info("Command /%s invoked by user %s in %s %s", command_name, user_id, chat_type, chat_id)


def _rate_limited(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        key = (
            update.effective_user.id
            if update.effective_user is not None
            else update.effective_chat.id
        )
        if not telegram_limiter.allow(f"telegram:{key}"):
            logger.info("Rate limited user/chat %s", key)
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
    "• /top <n> — show the n most recent notifications, newest first "
    "(1–100)\n"
    "• /about — learn what this bot is about and find useful links\n"
    "• /donate — show ways to support VoucherBot\n"
    "• /stop — unsubscribe and delete your stored data\n"
    "• /help — show this message\n\n"
    "<b>Behaviour</b>\n"
    "• If I'm in a group chat, new alerts are posted there automatically.\n"
    "• In a private chat, new alerts are sent to you after /start.\n"
    "• Commands work in private chats and groups.\n"
    "• Unsubscribing does not delete earlier messages you received.\n\n"
    "<b>Links</b>\n"
    "• Privacy policy: <a href=\"https://voucherbot.pages.dev/#telegram/privacy\">"
    "voucherbot.pages.dev/#telegram/privacy</a>\n"
    "• Terms of service: <a href=\"https://voucherbot.pages.dev/#telegram/terms\">"
    "voucherbot.pages.dev/#telegram/terms</a>\n"
    "• Disclaimer: <a href=\"https://voucherbot.pages.dev/#telegram/disclaimer\">"
    "voucherbot.pages.dev/#telegram/disclaimer</a>\n"
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
    "<b><a href=\"https://voucherbot.pages.dev/\">voucherbot.pages.dev</a></b>\n\n"
    "<b>What I do here</b>\n"
    "• Push each new listing to this private chat (after /start) and to any group "
    "I'm added to.\n"
    "• Answer on-demand queries: /latest for the newest post, /top <n> for the "
    "recent ones.\n"
    "• Deliver each alert exactly once — retries are deduplicated.\n"
    "• Stay privacy-first: /stop erases your subscription data anytime.\n\n"
    "<b>Source code</b>\n"
    "The collection pipeline is open source: "
    "<a href=\"https://github.com/Devathmaj/VoucherBot\">github.com/Devathmaj/VoucherBot</a>\n\n"
    "<b>Commands</b>\n"
    "Use /help to see all available commands and what they do.\n"
    "Support the developers by checking out /donate."
)

DONATE_TEXT = (
    "<b>Support VoucherBot</b>\n\n"
    "VoucherBot automatically discovers certification discounts, free exam vouchers, "
    "beta exam opportunities, and training promotions — and pushes them to you "
    "the moment they appear. It runs 24/7 so you never miss a deal.\n\n"
    "After setting up the notification service, the Render free tier no longer covers "
    "two instances running around the clock. Your support helps keep everything "
    "online and growing.\n\n"
    "<b>Ways to support</b>\n"
    "• <a href=\"https://buymeacoffee.com/devathmaj\"><b>Buy Me a Coffee</b></a> — A quick one-time thank-you — like buying the developer a coffee.\n"
    "• <a href=\"https://paypal.me/Devathmaj\"><b>PayPal</b></a> — Send a one-time donation of any amount via PayPal.\n"
    "• <a href=\"https://www.patreon.com/cw/devathmaj\"><b>Patreon</b></a> — Subscribe for ongoing support and behind-the-scenes updates.\n"
    "• <b>UPI</b> — Send directly via any UPI app (ID: <code>devathmaj@oksbi</code>).\n\n"
    "<b>Every bit helps</b>\n"
    "Even a small contribution goes a long way — it covers server costs, keeps the "
    "notification bots running, and lets us add new certification sources and features. "
    "If VoucherBot has helped you save on an exam, consider giving back so it can "
    "help others too.\n\n"
    "Thank you for being part of the community."
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


async def _send_with_keyboard(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    parse_mode: str | None = "HTML",
) -> None:
    """Send a message with the main inline keyboard attached."""
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=MAIN_KEYBOARD
    )


async def _do_latest(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Core logic for /latest command and callback."""
    posts = await fetch_latest_posts(limit=1)
    if not posts:
        await context.bot.send_message(chat_id=chat_id, text="No notifications yet.")
        return
    await context.bot.send_message(
        chat_id=chat_id, text=render_post_message(posts[0]), parse_mode="HTML", reply_markup=MAIN_KEYBOARD
    )


async def _do_help(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Core logic for /help command and callback."""
    await context.bot.send_message(
        chat_id=chat_id, text=HELP_TEXT, parse_mode="HTML", reply_markup=MAIN_KEYBOARD
    )


async def _do_about(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Core logic for /about command and callback."""
    await context.bot.send_message(
        chat_id=chat_id, text=ABOUT_TEXT, parse_mode="HTML", reply_markup=MAIN_KEYBOARD
    )


async def _do_donate(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Core logic for /donate command and callback."""
    await context.bot.send_message(
        chat_id=chat_id, text=DONATE_TEXT, parse_mode="HTML", reply_markup=MAIN_KEYBOARD
    )


@_rate_limited
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "start")
    user = update.effective_user
    chat = update.effective_chat
    await upsert_telegram_user(
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    logger.info("User %s subscribed in chat %s", user.id, redact_chat_id(chat.id))
    first = user.first_name or "there"
    await context.bot.send_message(
        chat_id=chat.id,
        text=(
            f"Hi {first}! You are now subscribed to notifications here.\n\n"
            "Use /latest for the newest post, /top <n> for recent ones, "
            "/about to learn what this bot is about, and /help for more information."
        ),
        reply_markup=MAIN_KEYBOARD,
    )


@_rate_limited
async def handle_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "latest")
    await _do_latest(update.effective_chat.id, context)


@_rate_limited
async def handle_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "top")
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
    _log_command(update, "help")
    await _do_help(update.effective_chat.id, context)


@_rate_limited
async def handle_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "about")
    await _do_about(update.effective_chat.id, context)


@_rate_limited
async def handle_donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "donate")
    await _do_donate(update.effective_chat.id, context)


@_rate_limited
async def handle_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "stop")
    chat = update.effective_chat
    deleted = await delete_telegram_user(chat.id)
    if deleted:
        logger.info("User %s unsubscribed and data deleted from chat %s", chat.id, redact_chat_id(chat.id))
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "You've been unsubscribed and your data has been deleted. "
                "Send /start anytime to resubscribe."
            ),
        )
    else:
        logger.info("User %s attempted to unsubscribe but was not subscribed in chat %s", chat.id, redact_chat_id(chat.id))
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


async def _handle_callback(query, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    """Route callback query to the appropriate handler."""
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    logger.info("Callback %s invoked by user %s in chat %s", action, user_id, redact_chat_id(chat_id))
    await query.answer()
    if action == "latest":
        await _do_latest(chat_id, context)
    elif action == "help":
        await _do_help(chat_id, context)
    elif action == "about":
        await _do_about(chat_id, context)
    elif action == "donate":
        await _do_donate(chat_id, context)


async def handle_callback_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_callback(update.callback_query, context, "latest")


async def handle_callback_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_callback(update.callback_query, context, "help")


async def handle_callback_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_callback(update.callback_query, context, "about")


async def handle_callback_donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_callback(update.callback_query, context, "donate")


def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", handle_start, filters=ChatType.PRIVATE))
    application.add_handler(CommandHandler("stop", handle_stop, filters=ChatType.PRIVATE))
    application.add_handler(CommandHandler("latest", handle_latest))
    application.add_handler(CommandHandler("top", handle_top))
    application.add_handler(CommandHandler("about", handle_about))
    application.add_handler(CommandHandler("donate", handle_donate))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CallbackQueryHandler(handle_callback_latest, pattern="^latest$"))
    application.add_handler(CallbackQueryHandler(handle_callback_help, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(handle_callback_about, pattern="^about$"))
    application.add_handler(CallbackQueryHandler(handle_callback_donate, pattern="^donate$"))
    application.add_handler(
        ChatMemberHandler(
            handle_my_chat_member, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER
        )
    )
