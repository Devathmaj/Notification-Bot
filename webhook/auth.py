from __future__ import annotations

from fastapi import Header, HTTPException, Request


async def ensure_valid_bearer(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    from config import settings

    expected = settings.webhook_secret
    if not expected:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")
