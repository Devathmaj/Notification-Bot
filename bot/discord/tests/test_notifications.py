from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from bot.discord.bot.notifications import build_post_embed, notify_for_post
from bot.discord.database.channel_targets import upsert_channel_target
from bot.discord.database.models import SentMessage
from bot.discord.database.preferences import set_dm


@pytest.fixture
def sample_post() -> dict:
    return {
        "id": 123,
        "post_id": 123,
        "title": "AWS Certification Voucher",
        "promotion_name": "AWS Certification Voucher",
        "promotion_type": "exam voucher",
        "url": "https://example.com/post",
        "registration_url": "https://example.com/register",
        "vendor": "aws",
        "discount": "50% off",
        "reason": "Save 50% off on AWS certification exams.",
        "voucher_code": "ABC123",
        "author": "Example Author",
        "published_at": "2026-08-15T10:30:00+00:00",
        "created_at": "2026-08-15T10:30:00+00:00",
        "ai_result": {
            "is_voucher": True,
            "promotion_name": "AWS Certification Voucher",
            "promotion_type": "exam",
            "voucher_code": "ABC123",
            "discount": "100%",
            "registration_url": "https://example.com/register",
            "vendor": "aws",
            "regions": ["Central & Eastern Europe"],
            "certifications": ["AWS Certified Solutions Architect"],
            "reason": "Valid certification promotion",
            "confidence": 0.97,
        },
    }


def test_build_post_embed_card(sample_post):
    embed = build_post_embed(sample_post)
    assert embed.title == "AWS Certification Voucher"
    assert embed.url == "https://example.com/register"
    assert "**Aws 50% off**" in embed.description
    assert "Save 50% off on AWS certification exams." in embed.description
    assert "Central & Eastern Europe" in embed.description
    assert "exam voucher" in embed.description
    field_names = [f.name for f in embed.fields]
    assert "Code" in field_names
    assert "ABC123" in str(embed.fields[0].value)
    assert embed.footer.text == "Aws · Confidence 0.97"


def _dm_client(user_id: int) -> MagicMock:
    client = MagicMock()
    client.get_user.return_value = None

    class FakeUser:
        id = user_id

        async def send(self, embed):
            return SimpleNamespace(id=42)

    client.fetch_user = AsyncMock(return_value=FakeUser())
    return client


async def test_notify_dm(db, sample_post):
    await set_dm(1001)
    client = _dm_client(1001)

    sent = await notify_for_post(client, sample_post)
    assert sent == 1

    async with db() as session:
        rows = (await session.execute(select(SentMessage))).scalars().all()
        assert len(rows) == 1
        assert rows[0].post_id == "123"
        assert rows[0].recipient_id == "1001"
        assert rows[0].delivery_kind == "dm"


async def test_notify_dedup(db, sample_post):
    await set_dm(1001)
    client = _dm_client(1001)

    sent1 = await notify_for_post(client, sample_post)
    sent2 = await notify_for_post(client, sample_post)
    assert sent1 == 1
    assert sent2 == 0  # no double-send on webhook retry


async def test_notify_channel_mentions_everyone(db, sample_post):
    await upsert_channel_target("111", "222", set_by_user_id=2001, mention="everyone")
    with patch(
        "bot.discord.bot.notifications._send_channel", new=AsyncMock(return_value=99)
    ) as send:
        sent = await notify_for_post(MagicMock(), sample_post)

    assert sent == 1
    send.assert_awaited_once()
    assert send.await_args.kwargs["content"] == "@everyone"


async def test_notify_channel_mentions_here(db, sample_post):
    await upsert_channel_target("111", "222", set_by_user_id=2003, mention="here")
    with patch(
        "bot.discord.bot.notifications._send_channel", new=AsyncMock(return_value=99)
    ) as send:
        sent = await notify_for_post(MagicMock(), sample_post)

    assert sent == 1
    send.assert_awaited_once()
    assert send.await_args.kwargs["content"] == "@here"


async def test_notify_channel_no_mention(db, sample_post):
    await upsert_channel_target("111", "222", set_by_user_id=2002, mention="none")
    with patch(
        "bot.discord.bot.notifications._send_channel", new=AsyncMock(return_value=99)
    ) as send:
        sent = await notify_for_post(MagicMock(), sample_post)

    assert sent == 1
    send.assert_awaited_once()
    assert send.await_args.kwargs["content"] is None


async def test_one_feed_one_send_even_if_configured_by_multiple(db, sample_post):
    # Two users raced to configure the same channel -> still a single feed.
    await upsert_channel_target("111", "222", set_by_user_id=2011, mention="none")
    await upsert_channel_target("111", "222", set_by_user_id=2012, mention="none")

    channel_send = AsyncMock(side_effect=lambda *a, **k: 77)
    with patch("bot.discord.bot.notifications._send_channel", new=channel_send):
        sent = await notify_for_post(MagicMock(), sample_post)

    assert sent == 1
    assert channel_send.call_count == 1


async def test_dm_and_channel_both(db, sample_post):
    await set_dm(3001)
    await upsert_channel_target(
        "111", "222", set_by_user_id=3001, mention="everyone"
    )
    dm_send = AsyncMock(return_value=99)
    channel_send = AsyncMock(side_effect=lambda *a, **k: 77)

    with (
        patch("bot.discord.bot.notifications._send_dm", new=dm_send),
        patch("bot.discord.bot.notifications._send_channel", new=channel_send),
    ):
        sent_ = await notify_for_post(MagicMock(), sample_post)

    assert sent_ == 2
    dm_send.assert_awaited_once()
    assert channel_send.call_count == 1

    # Per-recipient dedup: retry sends neither again.
    with (
        patch("bot.discord.bot.notifications._send_dm", new=AsyncMock(return_value=99)),
        patch("bot.discord.bot.notifications._send_channel", new=channel_send),
    ):
        again = await notify_for_post(MagicMock(), sample_post)
    assert again == 0
