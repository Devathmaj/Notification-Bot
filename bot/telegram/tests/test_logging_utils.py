from bot.telegram.bot.logging_utils import redact_chat_id


def test_redact_chat_id_hides_raw_value():
    raw = redact_chat_id(123456789)
    assert str(123456789) not in raw
    assert raw.startswith("chat_")


def test_redact_chat_id_is_stable_one_way():
    assert redact_chat_id(42) == redact_chat_id(42)
    assert redact_chat_id(42) != redact_chat_id(43)
    import hashlib

    assert redact_chat_id(42) == "chat_" + hashlib.sha256(b"42").hexdigest()[:12]
