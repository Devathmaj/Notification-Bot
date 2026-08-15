from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Shared runtime settings loaded from root .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Discord
    discord_token: str = Field(default="", description="Discord bot token")

    # Telegram
    telegram_http_api_token: str = Field(default="", description="Telegram bot token (BotFather)")
    telegram_http_api_base_url: str | None = Field(
        default=None,
        description="Base URL of a self-hosted Telegram HTTP API server, if any",
    )
    telegram_webhook_url: str = Field(
        default="",
        description="Full public https URL where Telegram POSTs updates (*/telegram/webhook)",
    )
    telegram_webhook_secret: str = Field(
        default="",
        description=(
            "Secret token passed to setWebhook and checked via the "
            "X-Telegram-Bot-Api-Secret-Token header"
        ),
    )

    # Webhook server
    webhook_secret: str = Field(default="", description="Bearer secret for incoming webhooks")
    webhook_rate_limit: str = Field(
        default="10/minute", description="Per-IP limit on POST /webhook"
    )
    health_rate_limit: str = Field(default="30/minute", description="Per-IP limit on GET /health")
    webhook_host: str = Field(default="0.0.0.0", description="Bind host for the webhook server")
    webhook_port: int = Field(default=43217, description="Bind port for the webhook server")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:PASSWORD@localhost:5432/postgres",
        description="Async SQLAlchemy database URL",
    )
    db_app_user: str | None = Field(
        default=None, description="Postgres role granted DML on owned tables"
    )

    @property
    def has_discord_token(self) -> bool:
        return bool(self.discord_token)

    @property
    def has_telegram_token(self) -> bool:
        return bool(self.telegram_http_api_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
