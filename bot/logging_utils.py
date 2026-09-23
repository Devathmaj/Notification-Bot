from __future__ import annotations

import hashlib
import logging
import re
from logging import LogRecord
from typing import Any

_DISCORD_TOKEN_PATTERN = re.compile(r"Bot\s+([A-Za-z0-9._-]{20,})")
_TELEGRAM_TOKEN_PATTERN = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{34,}")
_REDACT_LENGTH = 12


def redact_chat_id(chat_id: int) -> str:
    """One-way hash of a chat id so log lines never expose the raw value."""
    digest = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()
    return f"chat_{digest[:_REDACT_LENGTH]}"


def redact_token(token: str) -> str:
    """Redact a token for safe logging, showing only first/last few chars."""
    if not token:
        return "<empty>"
    if len(token) <= 8:
        return "<redacted>"
    return f"{token[:4]}...{token[-4:]}"


def sanitize_message(message: str) -> str:
    """Remove tokens from a log message."""
    message = _DISCORD_TOKEN_PATTERN.sub(lambda m: f"Bot {redact_token(m.group(1))}", message)
    message = _TELEGRAM_TOKEN_PATTERN.sub(lambda m: redact_token(m.group(0)), message)
    return message


class TokenRedactingFilter(logging.Filter):
    """Logging filter that redacts bot tokens from all log records."""

    def filter(self, record: LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_message(record.msg)
        if record.args:
            record.args = tuple(
                sanitize_message(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Configure application-wide logging with token redaction."""
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.addFilter(TokenRedactingFilter())
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("slowapi").setLevel(logging.WARNING)