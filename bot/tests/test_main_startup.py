from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

import main


def _rate_limited() -> discord.HTTPException:
    return discord.HTTPException(MagicMock(status=429), {"message": "blocked"})


def _bot(side_effects) -> MagicMock:
    bot = MagicMock()
    bot.start = AsyncMock(side_effect=side_effects)
    bot.is_closed.return_value = True
    return bot


async def test_start_retries_transient_failure_then_succeeds(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_START_DELAYS", (0, 0))
    bot = _bot([_rate_limited(), None])

    await main._start_discord_with_retries(bot)

    assert bot.start.await_count == 2


async def test_start_gives_up_after_bounded_attempts(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_START_DELAYS", (0, 0, 0))
    bot = _bot(_rate_limited())

    # Bounded: returns instead of retrying forever or raising.
    await main._start_discord_with_retries(bot)

    assert bot.start.await_count == len(main._DISCORD_START_DELAYS)


async def test_bad_token_fails_fast_without_retries():
    bot = _bot(discord.LoginFailure("401"))

    await main._start_discord_with_retries(bot)

    assert bot.start.await_count == 1
