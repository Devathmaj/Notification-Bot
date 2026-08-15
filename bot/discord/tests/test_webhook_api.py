from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from config import settings
from webhook.server import create_app


@pytest.fixture
def client():
    settings.webhook_secret = "test-secret"
    app = create_app(MagicMock())
    with TestClient(app) as c:
        yield c
    settings.webhook_secret = ""


@pytest.fixture
def sample_payload():
    return {
        "event": "voucher_alert",
        "title": "Voucher: Aws — AWS Skill Builder Exam Voucher",
        "post": "https://example.com/post/1",
        "claim_url": "https://aws.amazon.com/skill-builder/",
        "confidence": 0.8,
        "sent_at": "2026-08-15T14:42:13.671939+00:00",
        "vendor": "aws",
        "promotion_name": "AWS Skill Builder Exam Voucher",
        "promotion_type": "voucher",
        "certifications": ["AWS-Developer"],
        "voucher_code": "FREE-AWS-DEV-2026",
        "discount": "100%",
        "regions": ["Global"],
        "reason": "Official AWS promotion",
    }


def _auth():
    return {"Authorization": f"Bearer {settings.webhook_secret}"}


def test_webhook_rejects_without_bearer(client, sample_payload):
    resp = client.post("/webhook", json=sample_payload)
    assert resp.status_code == 401


def test_webhook_rejects_wrong_bearer(client, sample_payload):
    resp = client.post("/webhook", json=sample_payload, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_webhook_rejects_wrong_event_type(client):
    resp = client.post("/webhook", json={"event": "something_else"}, headers=_auth())
    assert resp.status_code == 400


def test_webhook_rejects_missing_fields(client):
    resp = client.post("/webhook", json={"event": "voucher_alert"}, headers=_auth())
    assert resp.status_code == 400


def test_health_public_ok(client, monkeypatch):
    async def _ok() -> bool:
        return True

    monkeypatch.setattr("webhook.server._database_ok", _ok)
    assert client.get("/health").status_code == 200


def test_health_degraded_when_db_down(client, monkeypatch):
    async def _down() -> bool:
        return False

    monkeypatch.setattr("webhook.server._database_ok", _down)
    resp = client.get("/health")
    assert resp.status_code == 503


async def test_webhook_valid_event_dispatches_async(sample_payload, db):
    from bot.discord.database.preferences import set_dm
    from webhook.handlers import handle_event

    await set_dm(1001)

    client = MagicMock()
    client.get_user.return_value = None

    class FakeUser:
        id = 1001

        async def send(self, embed):
            return SimpleNamespace(id=42)

    client.fetch_user = AsyncMock(return_value=FakeUser())

    sent = await handle_event(sample_payload, client)
    assert sent == 1

    # Retry the same event: deduped.
    sent_again = await handle_event(sample_payload, client)
    assert sent_again == 0
