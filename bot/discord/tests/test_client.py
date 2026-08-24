from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from discord import app_commands

from bot.discord.bot.client import NotificationBot


def _interaction(is_done: bool = False) -> MagicMock:
    interaction = MagicMock()
    interaction.command = SimpleNamespace(qualified_name="latest")
    interaction.response.is_done.return_value = is_done
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _failure() -> app_commands.CommandInvokeError:
    # Real internals that must never reach the user.
    return app_commands.CommandInvokeError(
        SimpleNamespace(name="latest"),
        ValueError("postgres://app:secret@db.internal:5432/vouchers query failed"),
    )


async def test_tree_error_replies_generic_without_internals():
    bot = NotificationBot()
    interaction = _interaction()

    await bot.tree.on_error(interaction, _failure())

    args, kwargs = interaction.response.send_message.await_args
    text = args[0] if args else kwargs.get("content", "")
    assert "Something went wrong" in text
    assert "postgres" not in text.lower()
    assert "valueerror" not in text.lower()
    assert kwargs["ephemeral"] is True


async def test_tree_error_uses_followup_when_already_deferred():
    bot = NotificationBot()
    interaction = _interaction(is_done=True)

    await bot.tree.on_error(interaction, _failure())

    interaction.response.send_message.assert_not_called()
    args, kwargs = interaction.followup.send.await_args
    text = args[0] if args else kwargs.get("content", "")
    assert "Something went wrong" in text
    assert "postgres" not in text.lower()
    assert kwargs["ephemeral"] is True
