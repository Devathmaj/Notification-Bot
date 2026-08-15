from __future__ import annotations

import hashlib

_REDACT_LENGTH = 12


def redact_chat_id(chat_id: int) -> str:
    """One-way hash of a chat id so log lines never expose the raw value."""
    digest = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()
    return f"chat_{digest[:_REDACT_LENGTH]}"
