from bot.telegram.database.groups import (
    deactivate_telegram_group,
    list_active_groups,
    upsert_telegram_group,
)


async def test_upsert_creates_group(db):
    group = await upsert_telegram_group(
        chat_id=-1001, title="Announcements", chat_type="supergroup"
    )
    assert group.chat_id == -1001
    assert group.active is True
    groups = await list_active_groups()
    assert [g.chat_id for g in groups] == [-1001]


async def test_upsert_reactivates_deactivated(db):
    await upsert_telegram_group(chat_id=-1001, title="X", chat_type="supergroup")
    await deactivate_telegram_group(-1001)
    assert await list_active_groups() == []
    await upsert_telegram_group(chat_id=-1001, title="X", chat_type="supergroup")
    assert len(await list_active_groups()) == 1


async def test_deactivate_missing_returns_false(db):
    assert await deactivate_telegram_group(-999) is False


async def test_active_group_missing_chat_type_defaults(db):
    group = await upsert_telegram_group(chat_id=-1002, title="X")
    assert group.chat_type == "unknown"
