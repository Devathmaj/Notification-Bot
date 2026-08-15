import pytest

from bot.discord.tests.conftest import SAMPLE_EVENT, sample_event
from webhook.handlers import InvalidEvent, validate_event


def test_validate_event_ok():
    post = validate_event(SAMPLE_EVENT)
    assert post["id"] == "https://example.com/post/1"
    assert post["title"] == "Voucher: Aws — AWS Skill Builder Exam Voucher"
    assert post["url"] == "https://example.com/post/1"
    assert post["registration_url"] == "https://aws.amazon.com/skill-builder/"
    assert post["vendor"] == "aws"
    assert post["promotion_type"] == "voucher"
    assert post["voucher_code"] == "FREE-AWS-DEV-2026"
    assert post["discount"] == "100%"
    assert post["ai_result"]["confidence"] == 0.8
    assert post["ai_result"]["certifications"] == ["AWS-Developer"]


def test_validate_event_rejects_wrong_event():
    with pytest.raises(InvalidEvent):
        validate_event(sample_event(event="other"))


def test_validate_event_rejects_missing_title():
    payload = sample_event()
    del payload["title"]
    with pytest.raises(InvalidEvent):
        validate_event(payload)


def test_validate_event_rejects_missing_post():
    payload = sample_event()
    del payload["post"]
    with pytest.raises(InvalidEvent):
        validate_event(payload)
