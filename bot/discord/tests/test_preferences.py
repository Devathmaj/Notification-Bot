from bot.discord.database.preferences import (
    delete_preference,
    disable_dm,
    get_preference,
    list_preferences,
    set_dm,
)


async def test_set_dm_enables_dm(db):
    pref = await set_dm(101)
    assert pref.user_id == 101
    assert pref.dm_enabled is True
    found = await get_preference(101)
    assert found.dm_enabled is True


async def test_disable_dm(db):
    await set_dm(202)
    await disable_dm(202)
    found = await get_preference(202)
    assert found.dm_enabled is False


async def test_get_missing_returns_none(db):
    assert await get_preference(9999) is None


async def test_bigint_snowflake_user_id(db):
    snowflake = 485079425931673600
    await set_dm(snowflake)
    found = await get_preference(snowflake)
    assert found.user_id == snowflake


async def test_list_preferences(db):
    await set_dm(1)
    await set_dm(2)
    prefs = await list_preferences()
    assert [p.user_id for p in prefs] == [1, 2]


async def test_delete_preference_removes_row(db):
    await set_dm(303)
    assert await delete_preference(303) is True
    assert await get_preference(303) is None


async def test_delete_preference_missing_returns_false(db):
    assert await delete_preference(9999) is False
