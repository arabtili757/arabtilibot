"""Tests verifying the fixes for /start command, promotional message editing, and safe delivery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from config import BotConfig, DEFAULT_SHARE_TEXT, DEFAULT_START_MESSAGE
from database.repository import SettingsRepository, UserRepository
from handlers.admin_handlers import AdminStates, create_admin_router
from handlers.user_handlers import complete_registration_and_respond, create_user_router
from services.broadcast_service import BroadcastService
from services.subscription_service import SubscriptionService
from tests.test_database_repository import AsyncMockDatabase
from utils.telegram_helpers import safe_send, safe_send_photo


@pytest.fixture
def test_env():
    db = AsyncMockDatabase()
    cfg = BotConfig(
        owner_ids=[5924300834],
        admin_ids=[5364318707],
        required_referrals=3,
        closed_channel_link="https://t.me/+marathon_link",
        subscription_check_enabled=True,
    )
    user_repo = UserRepository(db)
    settings_repo = SettingsRepository(db)
    broadcast_service = BroadcastService()
    return {
        "db": db,
        "cfg": cfg,
        "user_repo": user_repo,
        "settings_repo": settings_repo,
        "broadcast_service": broadcast_service,
    }


def test_subscribed_user_start_command_does_not_raise_value_error(test_env):
    """Ensure that when an already subscribed user runs /start, complete_registration_and_respond

    receives referral_service and executes without 'ValueError: Either result or referral_service must be provided'.
    """
    async def _test():
        cfg = test_env["cfg"]
        user_repo = test_env["user_repo"]
        settings_repo = test_env["settings_repo"]

        await settings_repo.get_settings(cfg)
        router = create_user_router(cfg, user_repo, settings_repo)

        # Find command_start_handler
        start_handler = None
        for handler in router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "command_start_handler":
                start_handler = handler.callback
                break
        assert start_handler is not None

        user_id = 888777
        user_msg = MagicMock()
        user_msg.from_user.id = user_id
        cmd_obj = MagicMock()
        cmd_obj.args = None

        bot_mock = MagicMock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        bot_mock.send_photo = AsyncMock(return_value=MagicMock())
        bot_mock.send_media_group = AsyncMock(return_value=[MagicMock()])
        bot_mock.send_sticker = AsyncMock(return_value=MagicMock())

        # Simulate user is ALREADY subscribed (triggers line 72 of user_handlers.py)
        with patch.object(SubscriptionService, "is_subscribed", AsyncMock(return_value=True)):
            # This MUST NOT raise ValueError
            await start_handler(user_msg, cmd_obj, bot_mock)

        # Verify messages were sent: welcome header + promotional post
        assert bot_mock.send_message.call_count >= 2
        calls = [c[0][1] for c in bot_mock.send_message.call_args_list]
        welcome_call = calls[0]
        assert "Arab tili marafoniga xush kelibsiz" in welcome_call
        promo_kb = bot_mock.send_message.call_args_list[1][1]["reply_markup"]
        assert promo_kb is not None
        assert "Do'stlarga ulashish" in str(promo_kb)
        assert f"start%3D{user_id}" in str(promo_kb) or f"start={user_id}" in str(promo_kb)

    asyncio.run(_test())


def test_chat_member_updated_handler_completes_registration_safely(test_env):
    """Ensure automatic subscription verification in chat_member_updated_handler

    passes referral_service and successfully completes pending registration.
    """
    async def _test():
        cfg = test_env["cfg"]
        user_repo = test_env["user_repo"]
        settings_repo = test_env["settings_repo"]

        settings = await settings_repo.get_settings(cfg)
        router = create_user_router(cfg, user_repo, settings_repo)

        chat_handler = None
        for handler in router.chat_member.handlers:
            if getattr(handler.callback, "__name__", "") == "chat_member_updated_handler":
                chat_handler = handler.callback
                break
        assert chat_handler is not None

        user_id = 999111
        # Create user as pending
        await user_repo.save_pending_user(user_id=user_id, pending_referrer_id=None)

        # Mock chat member event from a channel configured as mandatory
        mandatory_ch_id = settings.mandatory_channels[0].id if settings.mandatory_channels else -100123
        if not settings.mandatory_channels:
            from database.models import ChannelModel
            await settings_repo.add_channel(ChannelModel(name="TestCh", url="https://t.me/test", id=mandatory_ch_id))

        event = MagicMock()
        event.chat.id = mandatory_ch_id
        event.new_chat_member.user.is_bot = False
        event.new_chat_member.user.id = user_id

        bot_mock = MagicMock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        bot_mock.send_photo = AsyncMock(return_value=MagicMock())
        bot_mock.send_media_group = AsyncMock(return_value=[MagicMock()])
        bot_mock.send_sticker = AsyncMock(return_value=MagicMock())

        with patch.object(SubscriptionService, "is_subscribed", AsyncMock(return_value=True)):
            # Must complete without ValueError
            await chat_handler(event, bot_mock)

        # Verify user is now completed
        user = await user_repo.get_user(user_id)
        assert user["status"] == "completed"

    asyncio.run(_test())


def test_admin_edit_promotional_text_and_delivery(test_env):
    """Ensure that editing the promotional text ('Asosiy xabarni tahrirlash')

    works via admin panel and the new text is formatted with the user's link on /start.
    """
    async def _test():
        cfg = test_env["cfg"]
        user_repo = test_env["user_repo"]
        settings_repo = test_env["settings_repo"]
        broadcast_service = test_env["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)
        user_router = create_user_router(cfg, user_repo, settings_repo)

        # Find promotional text handlers in admin_router
        edit_button_handler = None
        input_handler = None
        confirm_handler = None

        for handler in admin_router.callback_query.handlers:
            name = getattr(handler.callback, "__name__", "")
            if name == "cb_edit_promo_text":
                edit_button_handler = handler.callback
            elif name == "cb_promo_confirm":
                confirm_handler = handler.callback

        for handler in admin_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "msg_receive_promo_text":
                input_handler = handler.callback

        assert edit_button_handler is not None, "cb_edit_promo_text handler not found"
        assert input_handler is not None, "msg_receive_promo_text handler not found"
        assert confirm_handler is not None, "cb_promo_confirm handler not found"

        # 1. Admin clicks "📝 Asosiy xabarni tahrirlash"
        cb_click = MagicMock()
        cb_click.from_user.id = 5924300834
        cb_click.answer = AsyncMock()
        cb_click.message.edit_text = AsyncMock()
        state = MagicMock()
        state.set_state = AsyncMock()
        state.update_data = AsyncMock()
        state.clear = AsyncMock()

        await edit_button_handler(cb_click, state)
        state.set_state.assert_called_with(AdminStates.waiting_for_promo_text)

        # 2. Admin inputs new promo text containing {link}
        new_promo = (
            "🔥 <b>YANGILANGAN MARAFON POSTI!</b>\n\n"
            "Marafonga qo'shilish uchun havola: {link}\n"
            "Do'stlaringizga ulashing!"
        )
        msg_promo = MagicMock()
        msg_promo.from_user.id = 5924300834
        msg_promo.html_text = new_promo
        msg_promo.text = new_promo
        msg_promo.answer = AsyncMock()

        bot_mock = MagicMock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())
        bot_mock.send_photo = AsyncMock(return_value=MagicMock())
        bot_mock.send_media_group = AsyncMock(return_value=[MagicMock()])
        bot_mock.send_sticker = AsyncMock(return_value=MagicMock())

        await input_handler(msg_promo, state, bot_mock)
        state.update_data.assert_called_with(pending_promo_text=new_promo)
        state.set_state.assert_called_with(AdminStates.waiting_for_promo_confirm)

        # 3. Admin confirms saving new promo text
        cb_confirm = MagicMock()
        cb_confirm.from_user.id = 5924300834
        cb_confirm.answer = AsyncMock()
        cb_confirm.message.edit_text = AsyncMock()
        state.get_data = AsyncMock(return_value={"pending_promo_text": new_promo})

        await confirm_handler(cb_confirm, state)
        updated_settings = await settings_repo.get_settings(cfg)
        assert updated_settings.share_text == new_promo

        # 4. User sends /start and receives the updated promo text with their personalized referral link
        start_handler = None
        for handler in user_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "command_start_handler":
                start_handler = handler.callback
                break

        user_id = 555666
        user_msg = MagicMock()
        user_msg.from_user.id = user_id
        cmd_obj = MagicMock()
        cmd_obj.args = None

        bot_mock.reset_mock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())

        with patch.object(SubscriptionService, "is_subscribed", AsyncMock(return_value=True)):
            await start_handler(user_msg, cmd_obj, bot_mock)

        # Second message sent is the promotional post
        promo_sent = bot_mock.send_message.call_args_list[-1][0][1]
        assert "YANGILANGAN MARAFON POSTI!" in promo_sent
        assert f"https://t.me/TestArabBot?start={user_id}" in promo_sent

    asyncio.run(_test())


def test_complete_registration_fault_tolerance(test_env):
    """Ensure complete_registration_and_respond handles missing referral_service

    without throwing ValueError, creating fallback or initializing service.
    """
    async def _test():
        cfg = test_env["cfg"]
        user_repo = test_env["user_repo"]
        settings_repo = test_env["settings_repo"]

        settings = await settings_repo.get_settings(cfg)
        bot_mock = MagicMock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())

        # Both referral_service=None and result=None, but user_repo provided
        await complete_registration_and_respond(
            user_id=112233,
            bot=bot_mock,
            settings=settings,
            referral_service=None,
            result=None,
            user_repo=user_repo,
        )
        assert bot_mock.send_message.call_count >= 2

        # Both referral_service=None and result=None and user_repo=None
        bot_mock.reset_mock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="TestArabBot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())

        await complete_registration_and_respond(
            user_id=445566,
            bot=bot_mock,
            settings=settings,
            referral_service=None,
            result=None,
            user_repo=None,
        )
        assert bot_mock.send_message.call_count >= 2

    asyncio.run(_test())


def test_safe_send_html_parse_fallback():
    """Ensure safe_send automatically falls back to parse_mode=None if HTML parsing fails."""
    async def _test():
        bot_mock = MagicMock()
        # First call fails with parse entities error, second call succeeds
        bot_mock.send_message = AsyncMock(
            side_effect=[Exception("can't parse entities: Unexpected end tag"), MagicMock(message_id=99)]
        )

        res = await safe_send(bot_mock, 12345, "<b>unclosed tag", parse_mode="HTML")
        assert res is not None
        assert bot_mock.send_message.call_count == 2
        # Second call should have parse_mode=None
        second_call_kw = bot_mock.send_message.call_args_list[1][1]
        assert second_call_kw.get("parse_mode") is None

    asyncio.run(_test())


def test_admin_edit_promotional_text_without_link_placeholder(test_env):
    """Ensure admin can submit advertisement text WITHOUT any {link} placeholder,

    it saves cleanly, preserves HTML (bold, italic, blockquote), and /start attaches
    the 'Do'stlarga ulashish' button below the message.
    """
    async def _test():
        cfg = test_env["cfg"]
        user_repo = test_env["user_repo"]
        settings_repo = test_env["settings_repo"]
        broadcast_service = test_env["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)
        user_router = create_user_router(cfg, user_repo, settings_repo)

        edit_button_handler = None
        input_handler = None
        confirm_handler = None

        for handler in admin_router.callback_query.handlers:
            name = getattr(handler.callback, "__name__", "")
            if name == "cb_edit_promo_text":
                edit_button_handler = handler.callback
            elif name == "cb_promo_confirm":
                confirm_handler = handler.callback

        for handler in admin_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "msg_receive_promo_text":
                input_handler = handler.callback

        # 1. Admin inputs text with bold, italic, blockquote, but ZERO {link}
        plain_formatted_text = (
            "ARAB TILI MARAFONI 💡\n\n"
            "<b>15 KUNDA A1 DAN A2 SARI</b> 📈\n"
            "<i>Marafon boshlanish sanasi: 26-oktabr!</i>\n"
            "<blockquote>Faqat ayol va qizlar qo'shilsin</blockquote>\n\n"
            "Botdan ro'yxatdan o'ting va marafonga qo'shiling. 🤍"
        )
        assert "{link}" not in plain_formatted_text

        msg_promo = MagicMock()
        msg_promo.from_user.id = 5924300834
        msg_promo.html_text = plain_formatted_text
        msg_promo.text = plain_formatted_text
        msg_promo.answer = AsyncMock()

        state = MagicMock()
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        state.get_data = AsyncMock(return_value={"pending_promo_text": plain_formatted_text})
        state.clear = AsyncMock()

        bot_mock = MagicMock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="ArabiyaBoost_bot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())

        # Must NOT reject message or ask for {link}!
        await input_handler(msg_promo, state, bot_mock)
        state.update_data.assert_called_with(pending_promo_text=plain_formatted_text)
        state.set_state.assert_called_with(AdminStates.waiting_for_promo_confirm)

        # Confirm save
        cb_confirm = MagicMock()
        cb_confirm.from_user.id = 5924300834
        cb_confirm.answer = AsyncMock()
        cb_confirm.message.edit_text = AsyncMock()
        await confirm_handler(cb_confirm, state)

        updated_settings = await settings_repo.get_settings(cfg)
        assert updated_settings.share_text == plain_formatted_text

        # 2. User sends /start and receives exact advertisement text with "Do'stlarga ulashish" button
        start_handler = None
        for handler in user_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "command_start_handler":
                start_handler = handler.callback
                break

        user_id = 123456789
        user_msg = MagicMock()
        user_msg.from_user.id = user_id
        cmd_obj = MagicMock()
        cmd_obj.args = None

        bot_mock.reset_mock()
        bot_mock.get_me = AsyncMock(return_value=MagicMock(username="ArabiyaBoost_bot"))
        bot_mock.send_message = AsyncMock(return_value=MagicMock())

        with patch.object(SubscriptionService, "is_subscribed", AsyncMock(return_value=True)):
            await start_handler(user_msg, cmd_obj, bot_mock)

        # Delivered promotional message
        promo_call = bot_mock.send_message.call_args_list[-1]
        sent_text = promo_call[0][1]
        sent_kb = promo_call[1]["reply_markup"]

        # Text matches exact formatting without forced link string appended
        assert sent_text == plain_formatted_text
        assert "<b>15 KUNDA A1 DAN A2 SARI</b>" in sent_text
        assert "<blockquote>Faqat ayol va qizlar qo'shilsin</blockquote>" in sent_text

        # "Do'stlarga ulashish" button is automatically attached with user's personal referral link
        assert sent_kb is not None
        button = sent_kb.inline_keyboard[0][0]
        assert "Do'stlarga ulashish" in button.text
        from urllib.parse import unquote
        assert f"https://t.me/ArabiyaBoost_bot?start={user_id}" in unquote(button.url)
        assert button.url.startswith("https://t.me/share/url?url=")

    asyncio.run(_test())
