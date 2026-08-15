from bot.discord.database.channel_targets import (
    get_channel_target,
    list_channel_targets,
    remove_channel_target,
    upsert_channel_target,
)


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
