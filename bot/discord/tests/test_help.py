from bot.discord.bot.commands import _HELP_URLS, build_help_embed


def test_help_embed_structure():
    embed = build_help_embed()
    assert embed.title == "Voucher Bot · Help"
    names = [field.name for field in embed.fields]
    assert names == [
        "🔍 Commands · Queries",
        "📣 Commands · Notifications",
        "🗑️ Commands · Data",
        "ℹ️ Behaviour",
        "⚖️ Legal",
    ]


def test_help_embed_mentions_commands_and_links():
    embed = build_help_embed()
    flat = " ".join(field.value for field in embed.fields)
    assert "/latest" in flat
    assert "/top" in flat
    assert "/notify dm" in flat
    assert "/notify channel" in flat
    assert "/notify list" in flat
    assert "/notify off" in flat
    assert "/delete" in flat
    assert "/help" in flat
    assert all(url in flat for url in _HELP_URLS.values())
