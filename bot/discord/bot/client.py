from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.discord.bot.commands import NotificationCommands

logger = logging.getLogger("discord.bot")

_BOT_STATUS = "/about | /help"

_ERROR_NOTICE = (
    "Something went wrong while running that command. Please try again in a moment."
)


class NotificationBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )
        # Log the real failure server-side; the user only ever sees a generic
        # notice with no details about internals.
        self.tree.on_error = self._on_tree_error

    async def _on_tree_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        command_name = getattr(interaction.command, "qualified_name", "<unknown>")
        logger.error("Slash command %s failed", command_name, exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(_ERROR_NOTICE, ephemeral=True)
            else:
                await interaction.response.send_message(_ERROR_NOTICE, ephemeral=True)
        except discord.HTTPException:
            logger.debug("Could not deliver the error notice for %s", command_name)

    async def setup_hook(self) -> None:
        await self.add_cog(NotificationCommands(self))
        await self.tree.sync()


def build_bot() -> NotificationBot:
    bot = NotificationBot()

    @bot.event
    async def on_ready() -> None:
        logger.info("Logged in as %s (id=%s)", bot.user, bot.user.id)
        try:
            await bot.change_presence(activity=discord.CustomActivity(name=_BOT_STATUS))
        except discord.HTTPException:
            logger.warning("Could not set the bot's custom status")

    return bot
