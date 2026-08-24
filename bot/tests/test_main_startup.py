from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import main


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.start = AsyncMock()
    return bot


def _record_sleeps(monkeypatch) -> list[int]:
    waits: list[int] = []
    monkeypatch.setattr(main, "_sleep", AsyncMock(side_effect=lambda s: waits.append(s)))
    return waits


async def test_starts_once_when_probe_succeeds(monkeypatch):
    monkeypatch.setattr(main, "_probe_discord_auth", AsyncMock(return_value=(200, None)))
    bot = _bot()

    await main._start_discord_when_ready(bot)

    assert bot.start.await_count == 1  # bootstrap runs exactly once


async def test_follows_discord_retry_after_instead_of_backoff(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_RETRY_BUFFER_SECONDS", 0)
    waits = _record_sleeps(monkeypatch)
    monkeypatch.setattr(
        main,
        "_probe_discord_auth",
        AsyncMock(side_effect=[(429, 1121), (429, 5), (200, None)]),
    )
    bot = _bot()

    await main._start_discord_when_ready(bot)

    # Waits exactly what Discord asked for — not the exponential schedule.
    assert waits == [1121, 5]
    bot.start.assert_awaited_once_with(main.settings.discord_token)


async def test_keeps_following_hints_until_connected(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_RETRY_BUFFER_SECONDS", 0)
    waits = _record_sleeps(monkeypatch)
    hints = [(429, h) for h in (900, 600, 300, 60, 30)]
    monkeypatch.setattr(
        main, "_probe_discord_auth", AsyncMock(side_effect=[*hints, (200, None)])
    )
    bot = _bot()

    await main._start_discord_when_ready(bot)

    assert waits == [900, 600, 300, 60, 30]
    assert bot.start.await_count == 1


async def test_server_hint_is_sanity_clamped(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_RETRY_BUFFER_SECONDS", 0)
    waits = _record_sleeps(monkeypatch)
    monkeypatch.setattr(
        main, "_probe_discord_auth", AsyncMock(side_effect=[(429, 4000), (200, None)])
    )
    bot = _bot()

    await main._start_discord_when_ready(bot)

    assert waits == [main._DISCORD_MAX_HINT_SECONDS]


async def test_falls_back_to_backoff_when_no_hint(monkeypatch):
    monkeypatch.setattr(main, "_DISCORD_FALLBACK_DELAYS", (7, 9))
    monkeypatch.setattr(main, "_DISCORD_MAX_FALLBACK_DELAY", 9)
    waits = _record_sleeps(monkeypatch)
    monkeypatch.setattr(
        main, "_probe_discord_auth", AsyncMock(side_effect=[(429, None), (429, None), (200, None)])
    )
    bot = _bot()

    await main._start_discord_when_ready(bot)

    assert waits == [7, 9]
    assert bot.start.await_count == 1


async def test_bad_token_fails_fast_without_retries():
    probe = AsyncMock(return_value=(401, None))
    bot = _bot()
    original_probe = main._probe_discord_auth
    main._probe_discord_auth = probe
    try:
        await main._start_discord_when_ready(bot)
    finally:
        main._probe_discord_auth = original_probe

    assert probe.await_count == 1
    assert bot.start.await_count == 0
