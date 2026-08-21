from bot.discord.bot.commands import (
    _HELP_URLS,
    _SOURCE_URL,
    _WEBSITE_URL,
    build_about_embed,
    build_help_embed,
)


def test_help_embed_structure():
    embed = build_help_embed()
    assert embed.title == "Voucher Bot · Help"
    names = [field.name for field in embed.fields]
    assert names == [
        "Commands · Queries",
        "Commands · Notifications",
        "Commands · Data",
        "Behaviour",
        "Legal",
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
    assert "/about" in flat
    assert "/help" in flat
    assert all(url in flat for url in _HELP_URLS.values())


def test_about_embed_structure():
    embed = build_about_embed()
    assert embed.title == "Voucher Bot · About"
    assert embed.url == _WEBSITE_URL
    names = [field.name for field in embed.fields]
    assert names == ["Website", "What I do here", "Source code", "Commands"]


def test_about_embed_content_is_prominent_and_complete():
    embed = build_about_embed()
    flat = " ".join(
        [embed.description or "", " ".join(field.value for field in embed.fields)]
    )
    # The website is the most prominent link.
    assert _WEBSITE_URL in (embed.description or "")
    first_field = embed.fields[0]
    assert first_field.name == "Website"
    assert _WEBSITE_URL in first_field.value
    # What the bot is about.
    assert "VoucherBot" in flat
    assert "open-source aggregator" in flat
    assert "certification discounts" in flat
    # Source code for the collection.
    assert _SOURCE_URL in flat
    # Points at /help for commands.
    assert "/help" in embed.fields[-1].value
