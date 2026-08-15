from __future__ import annotations

import pytest

from bot.rate_limit import WindowRateLimiter, parse_rate


def test_parse_rate_minute():
    assert parse_rate("10/minute") == (10, 60.0)


def test_parse_rate_defaults_to_minute():
    assert parse_rate("5") == (5, 60.0)


def test_parse_rate_hour():
    assert parse_rate("3/hour") == (3, 3600.0)


def test_parse_rate_rejects_unknown_unit():
    with pytest.raises(ValueError):
        parse_rate("5/lightyear")


def test_window_allows_up_to_max():
    limiter = WindowRateLimiter(3, 60.0)
    assert all(limiter.allow("u1") for _ in range(3))
    assert not limiter.allow("u1")


def test_window_is_per_key():
    limiter = WindowRateLimiter(1, 60.0)
    assert limiter.allow("u1")
    assert not limiter.allow("u1")
    assert limiter.allow("u2")


def test_zero_rate_allows_nothing():
    limiter = WindowRateLimiter(0, 60.0)
    assert not limiter.allow("u1")


def test_window_reset():
    limiter = WindowRateLimiter(1, 60.0)
    assert limiter.allow("u1")
    assert not limiter.allow("u1")
    limiter.reset("u1")
    assert limiter.allow("u1")
