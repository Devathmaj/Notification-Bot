from __future__ import annotations

import time
from collections import defaultdict, deque

RATE_LIMIT_TEXT = "You're going too fast. Please wait a moment and try again."

_UNIT_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}


def parse_rate(rate: str) -> tuple[int, float]:
    """Parse a slowapi-style ``"N/unit"`` rate into (max_calls, period_seconds)."""
    raw = rate.strip().split("/", 1)
    count = int(raw[0])
    unit = raw[1].lower() if len(raw) > 1 else "minute"
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"unsupported rate unit: {unit!r}")
    return count, float(_UNIT_SECONDS[unit])


class WindowRateLimiter:
    """Per-key sliding-window allowance.

    Safe for the app's single-threaded asyncio loop (discord gateway, telegram
    webhook and handlers all run on one process/loop).
    """

    def __init__(self, max_calls: int, period: float) -> None:
        if max_calls < 0:
            raise ValueError("max_calls must be >= 0")
        self.max_calls = max_calls
        self.period = period
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record a hit for ``key``; return True when it is within the window."""
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] >= self.period:
            window.popleft()
        if len(window) >= self.max_calls:
            return False
        window.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)
