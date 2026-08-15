from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ChatMemberHandler, CommandHandler, ContextTypes
from telegram.ext.filters import ChatType

from bot.discord.database.posts import fetch_latest_posts
from bot.telegram.bot.notifications import render_post_message
from bot.telegram.database.groups import deactivate_telegram_group, upsert_telegram_group
from bot.telegram.database.users import upsert_telegram_user

logger = logging.getLogger("telegram.bot.commands")

MAX_TOP = 100
_PACE_SECONDS = 0.35

_ADDED_STATUSES = {"member", "administrator", "restricted", "creator"}
_LEFT_STATUSES = {"left", "kicked"}

# TODO: replace the placeholders below with the bot's general behaviour notes.
HELP_TEXT = (
    "<b>Notification Bot</b>\n\n"
    "I watch for new voucher alerts on <i>this</i> service and deliver them to you "
    "directly or to any group I am added to.\n\n"
    "<b>Commands</b>\n"
    "• /start — subscribe to notifications in this chat\n"
    "• /latest — show the newest notification\n"
    "• /top &lt;n&gt; — show the n most recent notifications (1-100)\n"
    "• /help — this message\n\n"
    "<b>Behaviour</b>\n"
    "• If I'm in a group chat, new alerts are posted there automatically.\n"
    "• In a private chat, new alerts are sent to you after /start.\n"
    "• Commands can be used in group chats and private chats.\n\n"
    "<i>General info will be added here later.</i>"
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


async def handle_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    posts = await fetch_latest_posts(limit=1)
    if not posts:
        await _reply(update, context, "No notifications yet.")
        return
    await _reply(update, context, render_post_message(posts[0]), parse_mode="HTML")


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


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, context, HELP_TEXT, parse_mode="HTML")


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = update.my_chat_member
    if member is None:
        return
    chat = member.chat
    status = member.new_chat_member.status
    if status in _ADDED_STATUSES:
        await upsert_telegram_group(chat_id=chat.id, title=chat.title, chat_type=chat.type)
        logger.info("Bot added to chat %s (%s)", chat.id, chat.type)
    elif status in _LEFT_STATUSES:
        await deactivate_telegram_group(chat.id)
        logger.info("Bot removed from chat %s", chat.id)


def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", handle_start, filters=ChatType.PRIVATE))
    application.add_handler(CommandHandler("latest", handle_latest))
    application.add_handler(CommandHandler("top", handle_top))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(
        ChatMemberHandler(
            handle_my_chat_member, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER
        )
    )
