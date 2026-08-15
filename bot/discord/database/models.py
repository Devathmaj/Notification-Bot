from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DeliveryMethod(StrEnum):
    dm = "dm"
    channel = "channel"


class Preference(Base):
    """Per-user DM delivery flag."""

    __tablename__ = "preferences"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    dm_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChannelTarget(Base):
    """One shared feed per channel (guild + channel). Configured by an admin,
    feeds each post to the channel once regardless of how many users opted in."""

    __tablename__ = "channel_targets"
    __table_args__ = (
        UniqueConstraint("guild_id", "channel_id", name="uq_channel_target_guild_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(20), nullable=False)
    set_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mention: Mapped[str] = mapped_column(String(10), default="none", server_default=text("'none'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SentMessage(Base):
    """Dedup + audit log: one row per delivered (recipient kind, post, recipient).

    recipient_id is the user snowflake for DMs and the channel snowflake for
    channel feeds, so each is deduped independently.
    """

    __tablename__ = "sent_messages"
    __table_args__ = (
        UniqueConstraint(
            "platform", "delivery_kind", "post_id", "recipient_id",
            name="uq_sent_kind_platform_post_recipient",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), index=True, default="discord")
    delivery_kind: Mapped[str] = mapped_column(
        String(10), default="dm", server_default=text("'dm'")
    )
    post_id: Mapped[str] = mapped_column(String(512), index=True)
    recipient_id: Mapped[str] = mapped_column(String(40), index=True)
    guild_id: Mapped[int | None] = mapped_column(String(20), nullable=True)
    discord_message_id: Mapped[int | None] = mapped_column(String(20), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    preference_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("preferences.user_id", ondelete="CASCADE"),
        nullable=True,
    )
