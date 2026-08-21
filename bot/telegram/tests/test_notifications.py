from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from bot.discord.database.models import SentMessage
from bot.telegram.bot.notifications import notify_for_post, render_post_message
from bot.telegram.database.groups import upsert_telegram_group
from bot.telegram.database.users import upsert_telegram_user


def _fake_application():
    app = MagicMock()
    app.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=42))
    return app


def test_render_post_message(sample_post):
    text = render_post_message(sample_post)
    assert '<a href="https://example.com/register">AWS Certification Voucher</a>' in text
    assert "<b>AWS · 50% off</b>" in text
    assert "Save 50% off on AWS certification exams." in text
    assert "Type: Exam voucher" in text
    assert "Regions: Central &amp; Eastern Europe" in text
    assert "ABC123" in text
    # The AI assessment is framed separately, not mixed into the offer.
    assert text.startswith("<b><a href")
    assert "Why it was flagged:" in text
    assert "AI · High confidence · not a verification of the offer" in text
    assert '<a href="https://example.com/register">Open the original source</a>' in text


@patch("bot.telegram.bot.notifications.asyncio.sleep", new=AsyncMock())
async def test_notify_dm(db, sample_post):
    await upsert_telegram_user(chat_id=1001, user_id=1001)
    app = _fake_application()

    sent = await notify_for_post(app, sample_post)
    assert sent == 1
    app.bot.send_message.assert_awaited_once()
    assert app.bot.send_message.await_args.kwargs["chat_id"] == 1001
    assert app.bot.send_message.await_args.kwargs["parse_mode"] == "HTML"

    async with db() as session:
        rows = (await session.execute(select(SentMessage))).scalars().all()
        assert len(rows) == 1
        assert rows[0].platform == "telegram"
        assert rows[0].delivery_kind == "dm"
        assert rows[0].post_id == "123"
        assert rows[0].recipient_id == "1001"
        assert rows[0].telegram_message_id == "42"


@patch("bot.telegram.bot.notifications.asyncio.sleep", new=AsyncMock())
async def test_notify_group(db, sample_post):
    await upsert_telegram_group(chat_id=-1001, title="X", chat_type="supergroup")
    app = _fake_application()

    sent = await notify_for_post(app, sample_post)
    assert sent == 1
    assert app.bot.send_message.await_args.kwargs["chat_id"] == -1001

    async with db() as session:
        rows = (await session.execute(select(SentMessage))).scalars().all()
        assert rows[0].delivery_kind == "channel"
        assert rows[0].recipient_id == "-1001"


@patch("bot.telegram.bot.notifications.asyncio.sleep", new=AsyncMock())
async def test_notify_both(db, sample_post):
    await upsert_telegram_user(chat_id=1001, user_id=1001)
    await upsert_telegram_group(chat_id=-1001, title="X", chat_type="supergroup")
    app = _fake_application()

    sent = await notify_for_post(app, sample_post)
    assert sent == 2
    assert app.bot.send_message.call_count == 2


@patch("bot.telegram.bot.notifications.asyncio.sleep", new=AsyncMock())
async def test_notify_dedup(db, sample_post):
    await upsert_telegram_user(chat_id=1001, user_id=1001)
    app = _fake_application()

    assert await notify_for_post(app, sample_post) == 1
    assert await notify_for_post(app, sample_post) == 0
    app.bot.send_message.assert_awaited_once()


async def test_notify_no_recipients(db, sample_post):
    app = _fake_application()
    assert await notify_for_post(app, sample_post) == 0
    app.bot.send_message.assert_not_called()
