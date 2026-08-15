from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from telegram import Bot

from config import settings
from webhook.server import create_app

_FAKE_TOKEN = "1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _tg_app_mock():
    app = MagicMock()
    app.bot = Bot(_FAKE_TOKEN)
    app.process_update = AsyncMock()
    return app


def _update_payload() -> dict:
    return {
        "update_id": 100,
        "message": {
            "message_id": 1,
            "date": 1720000000,
            "chat": {"id": 7, "type": "private", "first_name": "Alice"},
            "from": {"id": 7, "is_bot": False, "first_name": "Alice"},
            "text": "hello",
        },
    }


@pytest.fixture
def client():
    settings.telegram_webhook_secret = ""
    app = create_app(MagicMock(), telegram_application=None)
    with TestClient(app) as c:
        yield c
    settings.telegram_webhook_secret = ""


def test_telegram_webhook_disabled_returns_503(client):
    resp = client.post("/telegram/webhook", json=_update_payload())
    assert resp.status_code == 503


def test_telegram_webhook_ok(client):
    app = _tg_app_mock()
    app_created = create_app(MagicMock(), telegram_application=app)
    with TestClient(app_created) as c:
        resp = c.post("/telegram/webhook", json=_update_payload())
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    app.process_update.assert_awaited_once()


def test_telegram_webhook_secret_header(client):
    settings.telegram_webhook_secret = "s3cret"
    app = _tg_app_mock()
    app_created = create_app(MagicMock(), telegram_application=app)
    with TestClient(app_created) as c:
        missing = c.post("/telegram/webhook", json=_update_payload())
        wrong = c.post(
            "/telegram/webhook",
            json=_update_payload(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
        )
        ok = c.post(
            "/telegram/webhook",
            json=_update_payload(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert app.process_update.await_count == 1
