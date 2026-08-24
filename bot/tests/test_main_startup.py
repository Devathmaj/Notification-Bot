from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import main


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.start = AsyncMock()
    return bot


async def test_starts_once_when_probe_succeeds(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_START_DELAYS", (0,))
    probe = AsyncMock(return_value=200)
    monkeypatch.setattr(main, "_probe_discord_auth", probe)
    bot = _bot()

    await main._start_discord_when_ready(bot)

    assert bot.start.await_count == 1  # bootstrap runs exactly once
    assert probe.await_count == 1


async def test_probes_until_ready_then_starts(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_START_DELAYS", (0, 0, 0))
    probe = AsyncMock(side_effect=[429, 429, 200])
    monkeypatch.setattr(main, "_probe_discord_auth", probe)
    bot = _bot()

    await main._start_discord_when_ready(bot)

    assert probe.await_count == 3
    assert bot.start.await_count == 1


async def test_gives_up_after_bounded_attempts(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_START_DELAYS", (0, 0))
    monkeypatch.setattr(main, "_probe_discord_auth", AsyncMock(return_value=429))
    bot = _bot()

    # Bounded: returns instead of probing forever or raising.
    await main._start_discord_when_ready(bot)

    assert bot.start.await_count == 0


async def test_bad_token_fails_fast_without_retries(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_START_DELAYS", (0, 0))
    monkeypatch.setattr(main, "_probe_discord_auth", AsyncMock(return_value=401))
    bot = _bot()

    await main._start_discord_when_ready(bot)

    assert bot.start.await_count == 0
