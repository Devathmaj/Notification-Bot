from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.discord.database.connection import dispose_engine, set_engine_for_tests
from bot.discord.database.models import Base
from bot.rate_limit import WindowRateLimiter
from bot.telegram.database import models as _telegram_models  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_telegram_limiter():
    from bot.telegram.bot import commands

    original = commands.telegram_limiter
    commands.telegram_limiter = WindowRateLimiter(10_000, 3600)
    yield
    commands.telegram_limiter = original


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_engine_for_tests(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await dispose_engine()


@pytest.fixture
def sample_post() -> dict:
    return {
        "id": 123,
        "post_id": 123,
        "title": "AWS Certification Voucher",
        "promotion_name": "AWS Certification Voucher",
        "promotion_type": "exam voucher",
        "url": "https://example.com/post",
        "registration_url": "https://example.com/register",
        "vendor": "aws",
        "discount": "50% off",
        "reason": "Save 50% off on AWS certification exams.",
        "voucher_code": "ABC123",
        "author": "Example Author",
        "published_at": "2026-08-15T10:30:00+00:00",
        "created_at": "2026-08-15T10:30:00+00:00",
        "ai_result": {
            "is_voucher": True,
            "promotion_name": "AWS Certification Voucher",
            "promotion_type": "exam",
            "voucher_code": "ABC123",
            "discount": "100%",
            "registration_url": "https://example.com/register",
            "vendor": "aws",
            "regions": ["Central & Eastern Europe"],
            "certifications": ["AWS Certified Solutions Architect"],
            "reason": "Valid certification promotion",
            "confidence": 0.97,
        },
    }
