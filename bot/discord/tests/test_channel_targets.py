from datetime import UTC

from sqlalchemy import select

from bot.discord.database.channel_targets import (
    delete_channel_targets_by_user,
    get_channel_target,
    list_channel_targets,
    purge_channel_sent_history,
    remove_channel_target,
    upsert_channel_target,
)
from bot.discord.database.models import DeliveryMethod, SentMessage


async def _add_sent(db, *, channel_id, guild_id="111", post_id="https://example.com/post/1"):
    from datetime import datetime

    async with db() as session:
        session.add(
            SentMessage(
                platform="discord",
                delivery_kind=DeliveryMethod.channel,
                post_id=post_id,
                recipient_id=channel_id,
                guild_id=guild_id,
                discord_message_id="42",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def test_upsert_creates_target(db):
    target = await upsert_channel_target("111", "222", set_by_user_id=1001, mention="everyone")
    assert target.guild_id == "111"
    assert target.channel_id == "222"
    assert target.set_by_user_id == 1001
    assert target.mention == "everyone"
    found = await get_channel_target("111", "222")
    assert found is not None


async def test_same_channel_is_single_feed(db):
    # Two users configure the same channel -> one shared feed, last config wins.
    await upsert_channel_target("111", "222", set_by_user_id=1001, mention="none")
    await upsert_channel_target("111", "222", set_by_user_id=2002, mention="here")
    targets = await list_channel_targets()
    assert len(targets) == 1
    assert targets[0].set_by_user_id == 2002
    assert targets[0].mention == "here"


async def test_list_by_setter(db):
    await upsert_channel_target("111", "222", set_by_user_id=1001)
    await upsert_channel_target("111", "333", set_by_user_id=2002)
    mine = await list_channel_targets(set_by_user_id=1001)
    assert [t.channel_id for t in mine] == ["222"]


async def test_remove_target(db):
    await upsert_channel_target("111", "222", set_by_user_id=1001)
    assert await remove_channel_target("111", "222") is True
    assert await remove_channel_target("111", "222") is False
    assert await get_channel_target("111", "222") is None


async def test_delete_targets_by_user_only_removes_own(db):
    await upsert_channel_target("111", "222", set_by_user_id=1001)
    await upsert_channel_target("111", "333", set_by_user_id=1001)
    await upsert_channel_target("222", "444", set_by_user_id=2002)

    removed = await delete_channel_targets_by_user(1001)
    assert removed == 2
    assert await list_channel_targets(set_by_user_id=1001) == []
    remaining = await list_channel_targets(set_by_user_id=2002)
    assert [t.channel_id for t in remaining] == ["444"]


async def test_delete_targets_by_user_missing_returns_zero(db):
    assert await delete_channel_targets_by_user(9999) == 0


async def test_purge_channel_history_removes_only_that_channel(db):
    await _add_sent(db, channel_id="222", post_id="https://example.com/post/1")
    await _add_sent(db, channel_id="222", post_id="https://example.com/post/2")
    await _add_sent(db, channel_id="333")

    removed = await purge_channel_sent_history("111", "222")
    assert removed == 2
    # Other channel's history untouched.
    async with db() as session:
        result = await session.execute(select(SentMessage.recipient_id))
        rows = result.scalars().all()
    assert rows == ["333"]


async def test_purge_channel_history_skips_dm_rows(db):
    async with db() as session:
        session.add(
            SentMessage(
                platform="discord",
                delivery_kind=DeliveryMethod.dm,
                post_id="https://example.com/post/1",
                recipient_id="222",
            )
        )
        await session.commit()

    assert await purge_channel_sent_history("111", "222") == 0
