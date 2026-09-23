from __future__ import annotations

import logging
from typing import Any

import discord
from fastapi import Depends, FastAPI, HTTPException, Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text
from starlette.responses import JSONResponse
from telegram import Update
from telegram.ext import Application

from config import settings
from webhook.auth import ensure_valid_bearer
from webhook.handlers import InvalidEvent, handle_event, validate_event

logger = logging.getLogger("webhook")

limiter = Limiter(key_func=get_remote_address)


async def _database_ok() -> bool:
    """Return True when the shared DB engine can answer a trivial query."""
    try:
        from bot.discord.database.connection import get_session_factory

        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Health check: database unreachable", exc_info=True)
        return False


def create_app(client: discord.Client, telegram_application: Application | None = None) -> FastAPI:
    app = FastAPI(title="Notification Webhook", version="0.1.0")
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Any:
        retry_after = getattr(exc, "retry_after", None)
        headers = {"Retry-After": str(int(retry_after)) if retry_after is not None else "60"}
        logger.warning("Rate limit exceeded for %s", request.client.host if request.client else "unknown")
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please slow down."},
            headers=headers,
        )

    @app.head("/health")
    @limiter.limit(settings.health_rate_limit)
    async def health(request: Request) -> dict[str, str]:
        if not await _database_ok():
            raise HTTPException(status_code=503, detail="Database unreachable")
        return {"status": "ok", "database": "ok"}

    @app.post("/webhook", dependencies=[Depends(ensure_valid_bearer)])
    @limiter.limit(settings.webhook_rate_limit)
    async def webhook(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        client_ip = request.client.host if request.client else "unknown"
        logger.info("Webhook received from %s", client_ip)
        try:
            validate_event(payload)
        except InvalidEvent as exc:
            logger.warning("Invalid webhook event from %s: %s", client_ip, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        sent = await handle_event(payload, client, telegram_application)
        logger.info("Webhook processed successfully, sent %d notifications", sent)
        return {"status": "ok", "sent": sent}

    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request) -> dict[str, str]:
        if telegram_application is None:
            raise HTTPException(status_code=503, detail="Telegram bot not configured")

        if settings.telegram_webhook_secret:
            token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if token != settings.telegram_webhook_secret:
                logger.warning("Invalid Telegram webhook secret from %s", request.client.host if request.client else "unknown")
                raise HTTPException(status_code=401, detail="Unauthorized")

        payload = await request.json()
        client_ip = request.client.host if request.client else "unknown"
        update_id = payload.get("update_id")
        message = payload.get("message") or payload.get("edited_message") or payload.get("channel_post") or payload.get("edited_channel_post")
        chat_id = message.get("chat", {}).get("id") if message else None
        text = message.get("text") if message else None
        logger.info("Telegram webhook received from %s: update_id=%s chat_id=%s text=%s", client_ip, update_id, chat_id, text[:50] if text else None)

        update = Update.de_json(payload, telegram_application.bot)
        await telegram_application.process_update(update)
        logger.debug("Telegram update %s processed", update_id)
        return {"status": "ok"}

    return app
