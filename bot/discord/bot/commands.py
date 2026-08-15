from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from bot.discord.bot.notifications import build_post_embed
from bot.discord.database.channel_targets import (
    delete_channel_targets_by_user,
    get_channel_target,
    list_channel_targets,
    purge_channel_sent_history,
    remove_channel_target,
    upsert_channel_target,
)
from bot.discord.database.models import DeliveryMethod
from bot.discord.database.posts import fetch_latest_posts
from bot.discord.database.preferences import (
    delete_preference,
    disable_dm,
    get_preference,
    set_dm,
)
from bot.rate_limit import RATE_LIMIT_TEXT, WindowRateLimiter, parse_rate
from config import settings

MAX_TOP = 100

_HELP_COLOR = 0x2ECC71

_HELP_URLS = {
    "privacy": "https://voucherbot-preview.pages.dev/#discord/privacy",
    "terms": "https://voucherbot-preview.pages.dev/#discord/terms",
    "disclaimer": "https://voucherbot-preview.pages.dev/#discord/disclaimer",
    "permissions": "https://voucherbot-preview.pages.dev/#discord/permissions",
}


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Voucher Bot · Help",
        description=(
            "I watch for new voucher alerts and deliver them to you directly in "
            "DMs or to server channels that have a feed configured."
        ),
        color=_HELP_COLOR,
    )

    embed.add_field(
        name="🔍 Commands · Queries",
        value=(
            "`/latest` — Fetch the newest notification with its full details "
            "(vendor, discount, voucher code, certifications, expiry).\n"
            "`/top <n>` — Fetch the `n` most recent notifications (1–100), "
            "newest first."
        ),
        inline=False,
    )
    embed.add_field(
        name="📣 Commands · Notifications",
        value=(
            "`/notify dm` — Send every new alert to your private chat.\n"
            "`/notify channel <channel> [mention]` — Post every new alert to a "
            "channel. Requires the **Manage Channels** permission; `mention` can "
            "be `none`, `here`, or `everyone`.\n"
            "`/notify list` — Show everything you currently have enabled.\n"
            "`/notify off <target> [channel]` — Turn off DMs or remove a channel "
            "feed."
        ),
        inline=False,
    )
    embed.add_field(
        name="🗑️ Commands · Data",
        value=(
            "`/delete` — Erase all your stored data: DM preference, channel "
            "feeds you created, and the associated delivery history.\n"
            "`/help` — Show this message."
        ),
        inline=False,
    )
    embed.add_field(
        name="ℹ️ Behaviour",
        value=(
            "• New alerts are posted automatically to every configured channel "
            "feed.\n"
            "• Private-chat alerts only arrive after you run `/notify dm`.\n"
            "• Removing a feed or your DMs does not delete messages you already "
            "received."
        ),
        inline=False,
    )
    embed.add_field(
        name="⚖️ Legal",
        value=(
            f"• [Privacy policy]({_HELP_URLS['privacy']})\n"
            f"• [Terms of service]({_HELP_URLS['terms']})\n"
            f"• [Disclaimer]({_HELP_URLS['disclaimer']})\n"
            f"• [Install permissions]({_HELP_URLS['permissions']})"
        ),
        inline=False,
    )
    return embed

discord_limiter = WindowRateLimiter(*parse_rate(settings.discord_command_rate))


async def _rate_limited(interaction: discord.Interaction) -> bool:
    """Consume the user's command budget; reply and return True when throttled."""
    if discord_limiter.allow(f"discord:{interaction.user.id}"):
        return False
    if not interaction.response.is_done():
        await interaction.response.send_message(RATE_LIMIT_TEXT, ephemeral=True)
    return True


class NotificationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="latest", description="Fetch the latest notification")
    async def latest(self, interaction: discord.Interaction) -> None:
        if await _rate_limited(interaction):
            return
        await interaction.response.defer(ephemeral=False)
        posts = await fetch_latest_posts(limit=1)
        if not posts:
            await interaction.followup.send("No notifications yet.")
            return
        embed = build_post_embed(posts[0])
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="help", description="Show the available commands and what the bot does"
    )
    async def help(self, interaction: discord.Interaction) -> None:
        if await _rate_limited(interaction):
            return
        await interaction.response.send_message(embed=build_help_embed(), ephemeral=False)

    @app_commands.command(name="top", description="Fetch the `n` most recent notifications (1-100)")
    @app_commands.describe(n="How many notifications to fetch")
    async def top(
        self, interaction: discord.Interaction, n: app_commands.Range[int, 1, MAX_TOP]
    ) -> None:
        if await _rate_limited(interaction):
            return
        await interaction.response.defer(ephemeral=False)
        posts = await fetch_latest_posts(limit=n)
        if not posts:
            await interaction.followup.send("No notifications yet.")
            return
        embeds = [build_post_embed(p) for p in posts]
        for i in range(0, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[i : i + 10])

    notify = app_commands.Group(
        name="notify",
        description="Choose where notification posts are delivered",
        guild_only=True,
    )

    @notify.command(name="dm", description="Deliver notifications to you via DM")
    async def notify_dm(self, interaction: discord.Interaction) -> None:
        await set_dm(interaction.user.id)
        await interaction.response.send_message(
            "Notifications will be sent to your DMs.", ephemeral=True
        )

    @notify.command(
        name="channel",
        description="Configure the channel feed for notifications (Manage Channels required)",
    )
    @app_commands.describe(
        channel="The channel to post notifications into",
        mention="Whether to mention members on each post",
    )
    async def notify_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        mention: Literal["none", "here", "everyone"] = "none",
    ) -> None:
        perms = channel.permissions_for(interaction.user)
        if not perms.manage_channels:
            await interaction.response.send_message(
                f"You need the 'Manage Channels' permission in {channel.mention} "
                "to set up a notification feed there.",
                ephemeral=True,
            )
            return
        if mention != "none" and not perms.mention_everyone:
            await interaction.response.send_message(
                f"You need the 'Mention @everyone, @here, and All Roles' permission "
                f"in {channel.mention} to enable @here/@everyone mentions.",
                ephemeral=True,
            )
            return

        await upsert_channel_target(
            str(interaction.guild.id),
            str(channel.id),
            interaction.user.id,
            mention=mention,
        )
        labels = {"none": "No mentions", "here": "@here", "everyone": "@everyone"}
        message = f"Notification feed configured for {channel.mention} · {labels[mention]}"
        if mention != "none" and not channel.permissions_for(interaction.guild.me).mention_everyone:
            message += (
                "\n\u26a0\ufe0f I don't have the 'Mention @everyone, @here, and All Roles' "
                "permission here, so the mention won't work."
            )
        await interaction.response.send_message(message, ephemeral=True)

    @notify.command(name="list", description="Show your current notification settings")
    async def notify_list(self, interaction: discord.Interaction) -> None:
        pref = await get_preference(interaction.user.id)
        my_targets = await list_channel_targets(set_by_user_id=interaction.user.id)
        mention_labels = {"none": "No mentions", "here": "@here", "everyone": "@everyone"}
        if (pref is None or not pref.dm_enabled) and not my_targets:
            await interaction.response.send_message(
                "You currently have no notifications enabled. "
                "Use `/notify dm` or `/notify channel` to set one up.",
                ephemeral=True,
            )
            return

        lines = []
        lines.append("**DMs** — " + ("✅ enabled" if pref and pref.dm_enabled else "off"))

        if my_targets:
            lines.append("**Channel feeds**")
            for target in my_targets:
                channel = None
                if interaction.guild:
                    channel = interaction.guild.get_channel(int(target.channel_id))
                chan_text = channel.mention if channel else f"<#{target.channel_id}>"
                lines.append(
                    f"• {chan_text} · {mention_labels.get(target.mention, target.mention)}"
                )
        else:
            lines.append("**Channel feeds** — none")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @notify.command(name="off", description="Turn notifications off for one delivery method")
    @app_commands.choices(
        target=[
            app_commands.Choice(name="DMs", value="dm"),
            app_commands.Choice(name="Channel", value="channel"),
        ]
    )
    @app_commands.describe(
        target="Which delivery to turn off",
        channel="The channel feed to remove (only needed for target: Channel)",
    )
    async def notify_off(
        self,
        interaction: discord.Interaction,
        target: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
    ) -> None:
        kind = DeliveryMethod(target.value)
        if kind == DeliveryMethod.dm:
            await disable_dm(interaction.user.id)
            await interaction.response.send_message(
                "Turned off DM notifications.", ephemeral=True
            )
            return

        if channel is None:
            await interaction.response.send_message(
                "Pick the channel whose feed you want to remove "
                "(e.g. `/notify off target: Channel channel: #announcements`).",
                ephemeral=True,
            )
            return
        target_row = await get_channel_target(str(interaction.guild.id), str(channel.id))
        if target_row is None:
            await interaction.response.send_message(
                f"No notification feed is configured for {channel.mention}.",
                ephemeral=True,
            )
            return
        perms = channel.permissions_for(interaction.user)
        if target_row.set_by_user_id != interaction.user.id and not perms.manage_channels:
            await interaction.response.send_message(
                f"Only the user who set up this feed or someone with "
                f"'Manage Channels' in {channel.mention} can remove it.",
                ephemeral=True,
            )
            return

        await remove_channel_target(str(interaction.guild.id), str(channel.id))
        await purge_channel_sent_history(str(interaction.guild.id), str(channel.id))
        await interaction.response.send_message(
            f"Removed the notification feed for {channel.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="delete",
        description="Delete all your stored notification data (DMs and channel feeds)",
    )
    async def delete_data(self, interaction: discord.Interaction) -> None:
        pref_removed = await delete_preference(interaction.user.id)
        my_targets = await list_channel_targets(set_by_user_id=interaction.user.id)
        feeds_removed = await delete_channel_targets_by_user(interaction.user.id)
        history_purged = 0
        for target in my_targets:
            history_purged += await purge_channel_sent_history(
                target.guild_id, target.channel_id
            )

        parts = []
        if pref_removed:
            parts.append("DM preference deleted")
        if feeds_removed:
            plural = "" if feeds_removed == 1 else "s"
            parts.append(f"{feeds_removed} channel feed deletion{plural}")
            history_plural = "" if history_purged == 1 else "s"
            parts.append(f"{history_purged} channel history removal{history_plural}")
        if not parts:
            message = "You have no stored notification data to delete."
        else:
            message = "Deleted your notification data: " + "; ".join(parts) + "."
        await interaction.response.send_message(message, ephemeral=True)
