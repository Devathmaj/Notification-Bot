from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot.telegram.bot.commands import (
    HELP_TEXT,
    handle_help,
    handle_latest,
    handle_my_chat_member,
    handle_start,
    handle_top,
)
from bot.telegram.database.groups import list_active_groups, upsert_telegram_group
from bot.telegram.database.users import get_telegram_user


def make_user(uid=1, username="alice", first_name="Alice", last_name=None):
    return SimpleNamespace(id=uid, username=username, first_name=first_name, last_name=last_name)


def make_update(chat_id=1, user=None, my_chat_member=None):
    user = user or make_user()
    chat = SimpleNamespace(id=chat_id, title=None, type="private")
    return SimpleNamespace(effective_chat=chat, effective_user=user, my_chat_member=my_chat_member)


def make_context(args=None):
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return SimpleNamespace(bot=bot, args=args or [])


async def test_start_subscribes_user(db):
    ctx = make_context()
    await handle_start(make_update(chat_id=1001, user=make_user(uid=42)), ctx)
    user = await get_telegram_user(1001)
    assert user is not None
    assert user.user_id == 42
    ctx.bot.send_message.assert_awaited_once()
    assert "subscribed" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_latest_no_posts(db):
    ctx = make_context()
    with patch(
        "bot.telegram.bot.commands.fetch_latest_posts", new=AsyncMock(return_value=[])
    ):
        await handle_latest(make_update(), ctx)
    assert ctx.bot.send_message.await_args.kwargs["text"] == "No notifications yet."


async def test_latest_sends_post(db, sample_post):
    ctx = make_context()
    with patch(
        "bot.telegram.bot.commands.fetch_latest_posts",
        new=AsyncMock(return_value=[sample_post]),
    ):
        await handle_latest(make_update(), ctx)
    assert ctx.bot.send_message.await_args.kwargs["parse_mode"] == "HTML"
    assert "AWS Certification Voucher" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_top_rejects_missing_arg(db):
    ctx = make_context(args=[])
    await handle_top(make_update(), ctx)
    assert "1 and 100" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_top_rejects_non_numeric(db):
    ctx = make_context(args=["abc"])
    await handle_top(make_update(), ctx)
    assert "1 and 100" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_top_rejects_out_of_range(db):
    ctx = make_context(args=["0"])
    await handle_top(make_update(), ctx)
    assert "1 and 100" in ctx.bot.send_message.await_args.kwargs["text"]

    ctx = make_context(args=["101"])
    await handle_top(make_update(), ctx)
    assert "1 and 100" in ctx.bot.send_message.await_args.kwargs["text"]


async def test_top_boundary_values_ok(db, sample_post):
    with (
        patch(
            "bot.telegram.bot.commands.fetch_latest_posts",
            new=AsyncMock(return_value=[sample_post]),
        ) as fetch,
        patch("bot.telegram.bot.commands.asyncio.sleep", new=AsyncMock()),
    ):
        ctx = make_context(args=["1"])
        await handle_top(make_update(), ctx)
        assert fetch.await_args.kwargs == {"limit": 1}

        ctx = make_context(args=["100"])
        await handle_top(make_update(), ctx)
        assert fetch.await_args.kwargs == {"limit": 100}


async def test_top_sends_one_message_per_post(db, sample_post):
    with (
        patch(
            "bot.telegram.bot.commands.fetch_latest_posts",
            new=AsyncMock(return_value=[sample_post] * 3),
        ),
        patch("bot.telegram.bot.commands.asyncio.sleep", new=AsyncMock()),
    ):
        ctx = make_context(args=["3"])
        await handle_top(make_update(), ctx)
    assert ctx.bot.send_message.call_count == 3


async def test_help_mentions_commands(db):
    ctx = make_context()
    await handle_help(make_update(), ctx)
    text = ctx.bot.send_message.await_args.kwargs["text"]
    assert "/latest" in text
    assert "/top" in text
    assert "/help" in text
    assert text == HELP_TEXT


async def test_my_chat_member_add_upserts_group(db):
    old_member = SimpleNamespace(status="left")
    new_member = SimpleNamespace(status="member")
    chat = SimpleNamespace(id=-1001, title="Announcements", type="supergroup")
    member = SimpleNamespace(chat=chat, old_chat_member=old_member, new_chat_member=new_member)
    update = SimpleNamespace(effective_chat=chat, effective_user=None, my_chat_member=member)

    await handle_my_chat_member(update, make_context())
    groups = await list_active_groups()
    assert [g.chat_id for g in groups] == [-1001]


async def test_my_chat_member_leave_deactivates_group(db):
    await upsert_telegram_group(chat_id=-1001, title="X", chat_type="supergroup")
    new_member = SimpleNamespace(status="left")
    chat = SimpleNamespace(id=-1001, title="X", type="supergroup")
    member = SimpleNamespace(chat=chat, old_chat_member=None, new_chat_member=new_member)
    update = SimpleNamespace(effective_chat=chat, effective_user=None, my_chat_member=member)

    await handle_my_chat_member(update, make_context())
    assert await list_active_groups() == []
