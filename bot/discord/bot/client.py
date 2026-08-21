from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.discord.bot.commands import NotificationCommands

logger = logging.getLogger("discord.bot")

_BOT_STATUS = "/about | /help | https://voucherbot-preview.pages.dev"


class NotificationBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )

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
