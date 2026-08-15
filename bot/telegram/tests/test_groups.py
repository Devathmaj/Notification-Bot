from bot.telegram.database.groups import (
    delete_telegram_group,
    list_active_groups,
    purge_group_sent_history,
    upsert_telegram_group,
)


async def _add_group_sent(db, chat_id: int, post_id: str = "https://example.com/post/1") -> None:
    from bot.discord.database.models import DeliveryMethod, SentMessage

    async with db() as session:
        session.add(
            SentMessage(
                platform="telegram",
                delivery_kind=DeliveryMethod.channel,
                post_id=post_id,
                recipient_id=str(chat_id),
                telegram_message_id="42",
            )
        )
        await session.commit()


async def test_upsert_creates_group(db):
    group = await upsert_telegram_group(
        chat_id=-1001, title="Announcements", chat_type="supergroup"
    )
    assert group.chat_id == -1001
    assert group.active is True
    groups = await list_active_groups()
    assert [g.chat_id for g in groups] == [-1001]


async def test_delete_removes_group(db):
    await upsert_telegram_group(chat_id=-1001, title="X", chat_type="supergroup")
    assert await delete_telegram_group(-1001) is True
    assert await list_active_groups() == []
    # Re-adding the bot recreates the row.
    await upsert_telegram_group(chat_id=-1001, title="X", chat_type="supergroup")
    assert len(await list_active_groups()) == 1


async def test_delete_missing_returns_false(db):
    assert await delete_telegram_group(-999) is False


async def test_active_group_missing_chat_type_defaults(db):
    group = await upsert_telegram_group(chat_id=-1002, title="X")
    assert group.chat_type == "unknown"


async def test_purge_group_history_removes_sent_rows(db):
    await _add_group_sent(db, -1001, post_id="https://example.com/post/1")
    await _add_group_sent(db, -1001, post_id="https://example.com/post/2")
    await _add_group_sent(db, -1002)

    removed = await purge_group_sent_history(-1001)
    assert removed == 2

    from sqlalchemy import select

    from bot.discord.database.models import SentMessage

    async with db() as session:
        result = await session.execute(select(SentMessage.recipient_id))
        remaining = result.scalars().all()
    assert remaining == ["-1002"]
