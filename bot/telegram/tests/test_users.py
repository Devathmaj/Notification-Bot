from sqlalchemy import select

from bot.discord.database.models import DeliveryMethod, SentMessage
from bot.telegram.database.users import (
    delete_telegram_user,
    get_telegram_user,
    list_telegram_users,
    upsert_telegram_user,
)


async def test_upsert_creates_user(db):
    user = await upsert_telegram_user(
        chat_id=111, user_id=222, username="alice", first_name="Alice", last_name="A."
    )
    assert user.chat_id == 111
    assert user.user_id == 222
    assert user.username == "alice"
    assert user.subscribed is True
    found = await get_telegram_user(111)
    assert found is not None
    assert found.user_id == 222


async def test_upsert_updates_existing(db):
    await upsert_telegram_user(chat_id=111, user_id=222, username="alice")
    await upsert_telegram_user(chat_id=111, user_id=222, username="alice2", first_name="Alice2")
    found = await get_telegram_user(111)
    assert found.username == "alice2"
    assert found.first_name == "Alice2"


async def test_list_subscribed_only(db):
    await upsert_telegram_user(chat_id=1, user_id=10)
    await upsert_telegram_user(chat_id=2, user_id=20, subscribed=False)
    users = await list_telegram_users()
    assert [u.chat_id for u in users] == [1]


async def test_bigint_chat_id(db):
    big = 1234567890123456789
    await upsert_telegram_user(chat_id=big, user_id=big)
    found = await get_telegram_user(big)
    assert found is not None
    assert found.chat_id == big


async def test_get_missing_returns_none(db):
    assert await get_telegram_user(9999) is None


async def test_delete_removes_user(db):
    await upsert_telegram_user(chat_id=111, user_id=222)
    assert await delete_telegram_user(111) is True
    assert await get_telegram_user(111) is None


async def test_delete_missing_returns_false(db):
    assert await delete_telegram_user(9999) is False


async def test_delete_preserves_delivery_logs(db):
    await upsert_telegram_user(chat_id=111, user_id=222)
    async with db() as session:
        session.add(
            SentMessage(
                platform="telegram",
                delivery_kind=DeliveryMethod.dm,
                post_id="123",
                recipient_id="111",
                telegram_message_id="42",
            )
        )
        await session.commit()

    assert await delete_telegram_user(111) is True

    async with db() as session:
        rows = (await session.execute(select(SentMessage))).scalars().all()
        assert len(rows) == 1
        assert rows[0].recipient_id == "111"
