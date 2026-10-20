"""Tests for user flows including subscription check logic and keyboard generation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from keyboards.user_keyboards import get_sub_keyboard
from services.subscription_service import SubscriptionService


def test_subscription_keyboard_removes_manual_button_by_default():
    channels = [
        {"name": "Ch 1", "url": "https://t.me/ch1", "id": -1001},
        {"name": "Ch 2", "url": "https://t.me/ch2", "id": -1002},
    ]

    # In the normal user experience, the manual "A'zo bo'ldim" button is removed
    kb = get_sub_keyboard(channels)
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    check_btns = [btn for btn in all_buttons if "A'zo bo'ldim" in btn.text]
    assert len(check_btns) == 0
    assert len(all_buttons) == 2


def test_subscription_keyboard_preserves_ref_id():
    channels = [
        {"name": "Ch 1", "url": "https://t.me/ch1", "id": -1001},
        {"name": "Ch 2", "url": "https://t.me/ch2", "id": -1002},
    ]

    # When fallback check button is explicitly requested, ref_id is preserved
    kb = get_sub_keyboard(channels, include_check_button=True, ref_id="555123")
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    check_btn = [btn for btn in all_buttons if "A'zo bo'ldim" in btn.text][0]
    assert check_btn.callback_data == "checksub_555123"

    # None referral becomes checksub_none
    kb_none = get_sub_keyboard(channels, include_check_button=True, ref_id=None)
    check_btn_none = [btn for row in kb_none.inline_keyboard for btn in row if "A'zo bo'ldim" in btn.text][0]
    assert check_btn_none.callback_data == "checksub_none"


def test_subscription_service_all_subscribed():
    async def _test():
        bot = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "member"
        bot.get_chat_member.return_value = member_mock

        channels = [{"id": -1001}, {"id": -1002}]
        result = await SubscriptionService.is_subscribed(bot, user_id=123, channels=channels, check_enabled=True)
        assert result is True
        assert bot.get_chat_member.call_count == 2

    asyncio.run(_test())


def test_subscription_service_user_left():
    async def _test():
        bot = AsyncMock()
        member_mock = MagicMock()
        member_mock.status = "left"
        bot.get_chat_member.return_value = member_mock

        channels = [{"id": -1001}]
        result = await SubscriptionService.is_subscribed(bot, user_id=123, channels=channels, check_enabled=True)
        assert result is False

    asyncio.run(_test())


def test_subscription_service_disabled_bypasses_check():
    async def _test():
        bot = AsyncMock()
        channels = [{"id": -1001}]
        result = await SubscriptionService.is_subscribed(bot, user_id=123, channels=channels, check_enabled=False)
        assert result is True
        bot.get_chat_member.assert_not_called()

    asyncio.run(_test())


def test_subscription_service_handles_channel_error_gracefully():
    async def _test():
        bot = AsyncMock()
        bot.get_chat_member.side_effect = Exception("Channel not accessible")

        channels = [{"id": -1001}]
        result = await SubscriptionService.is_subscribed(bot, user_id=123, channels=channels, check_enabled=True)
        assert result is False

    asyncio.run(_test())
