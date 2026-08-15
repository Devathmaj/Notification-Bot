from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.discord.database.connection import dispose_engine, set_engine_for_tests
from bot.discord.database.models import Base


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_engine_for_tests(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await dispose_engine()


SAMPLE_EVENT = {
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


def sample_event(**overrides) -> dict:
    payload = dict(SAMPLE_EVENT)
    payload.update(overrides)
    return payload
