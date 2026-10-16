"""Unit tests for configuration validation and security."""

import pytest
from pydantic import ValidationError
from config import BotConfig, ChannelConfig


def test_valid_config_loading():
    config = BotConfig(
        BOT_TOKEN="123:MOCK_TOKEN",
        ADMIN_IDS="111,222",
        REQUIRED_REFERRALS=5,
        CLOSED_CHANNEL_LINK="https://t.me/+valid_link",
        SUBSCRIPTION_CHECK_ENABLED=True,
        MANDATORY_CHANNELS='[{"name": "Ch", "url": "https://t.me/ch", "id": -100123}]',
    )
    assert config.bot_token == "123:MOCK_TOKEN"
    assert config.admin_ids == [111, 222]
    assert config.required_referrals == 5
    assert len(config.mandatory_channels) == 1
    assert config.is_admin(111) is True
    assert config.is_admin(333) is False


def test_secret_not_exposed_in_repr():
    token = "SECRET_BOT_TOKEN_12345"
    config = BotConfig(
        BOT_TOKEN=token,
        ADMIN_IDS="123",
    )
    rep = repr(config)
    assert token not in rep
    assert "BotConfig" in rep


def test_invalid_channel_url():
    with pytest.raises(ValidationError):
        ChannelConfig(name="Bad", url="https://youtube.com/not_telegram", id=-100)


def test_invalid_channel_id_zero():
    with pytest.raises(ValidationError):
        ChannelConfig(name="Bad", url="https://t.me/good", id=0)


def test_invalid_threshold_below_one():
    with pytest.raises(ValidationError):
        BotConfig(
            BOT_TOKEN="123:MOCK",
            ADMIN_IDS="123",
            REQUIRED_REFERRALS=0,
        )


def test_admin_ids_various_formats():
    c1 = BotConfig(BOT_TOKEN="1:x", ADMIN_IDS=123)
    assert c1.admin_ids == [123]

    c2 = BotConfig(BOT_TOKEN="1:x", ADMIN_IDS=" 123 , 456 , 789 ")
    assert c2.admin_ids == [123, 456, 789]

    c3 = BotConfig(BOT_TOKEN="1:x", ADMIN_IDS=[10, 20])
    assert c3.admin_ids == [10, 20]
