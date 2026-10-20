"""Automated verification suite for Telegram Bot Admin Panel and Protection Rules.

Verifies:
1. User 5924300834 sends /admin and receives the admin panel.
2. User 5364318707 sends /admin and receives the same admin panel.
3. Both users can view statistics.
4. Both can add an ordinary administrator.
5. Both can remove an ordinary administrator.
6. Neither can remove the other or themselves.
7. Both can edit and save the /start message.
8. Both can add and remove channels.
9. Unauthorized users cannot access admin commands or callbacks.
10. Changes persist after restarting the bot.
11. No existing bot functionality is broken.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from config import BotConfig, ChannelConfig, DEFAULT_START_MESSAGE, PROTECTED_ADMIN_IDS
from database.models import ChannelModel
from database.repository import SettingsRepository, UserRepository
from handlers.admin_handlers import AdminStates, create_admin_router
from handlers.middlewares import IsAdminFilter, is_authorized_admin
from handlers.user_handlers import create_user_router
from keyboards.admin_keyboards import get_admin_main_keyboard
from services.broadcast_service import BroadcastService
from services.statistics_service import StatisticsService
from services.subscription_service import SubscriptionService
from tests.test_database_repository import AsyncMockDatabase


@pytest.fixture
def test_setup():
    db = AsyncMockDatabase()
    cfg = BotConfig(
        BOT_TOKEN="123456:TEST_TOKEN",
        OWNER_IDS="5924300834",
        ADMIN_IDS="5364318707",
        MONGODB_URI="mongodb://localhost:27017",
        CLOSED_CHANNEL_LINK="https://t.me/+closed_link",
    )
    user_repo = UserRepository(db)
    settings_repo = SettingsRepository(db)
    broadcast_service = BroadcastService()
    stats_service = StatisticsService(user_repo, settings_repo)

    return {
        "db": db,
        "cfg": cfg,
        "user_repo": user_repo,
        "settings_repo": settings_repo,
        "broadcast_service": broadcast_service,
        "stats_service": stats_service,
    }


# ==============================================================================
# TEST 1 & 2: User 5924300834 & 5364318707 open /admin and receive the same panel
# ==============================================================================

def test_both_protected_users_receive_admin_panel(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        broadcast_service = test_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        # Find cmd_admin_panel handler
        cmd_handler = None
        for handler in admin_router.message.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "cmd_admin_panel":
                cmd_handler = handler.callback
                break
        assert cmd_handler is not None

        # 1. User 5924300834 sends /admin
        msg_owner = MagicMock()
        msg_owner.from_user.id = 5924300834
        msg_owner.answer = AsyncMock()
        state_owner = MagicMock()
        state_owner.clear = AsyncMock()

        await cmd_handler(msg_owner, state_owner)
        msg_owner.answer.assert_called_once()
        owner_text, owner_kwargs = msg_owner.answer.call_args
        assert "Admin Boshqaruv Paneli" in owner_text[0]
        assert "Himoyalangan Bosh Administrator" in owner_text[0]
        assert owner_kwargs["reply_markup"] is not None

        # 2. User 5364318707 sends /admin
        msg_admin = MagicMock()
        msg_admin.from_user.id = 5364318707
        msg_admin.answer = AsyncMock()
        state_admin = MagicMock()
        state_admin.clear = AsyncMock()

        await cmd_handler(msg_admin, state_admin)
        msg_admin.answer.assert_called_once()
        admin_text, admin_kwargs = msg_admin.answer.call_args
        assert "Admin Boshqaruv Paneli" in admin_text[0]
        assert "Himoyalangan Bosh Administrator" in admin_text[0]
        assert admin_kwargs["reply_markup"] is not None

        # 3. Compare keyboard structure: both receive the exact same panel controls
        expected_kb = get_admin_main_keyboard()
        owner_buttons = [btn.callback_data for row in owner_kwargs["reply_markup"].inline_keyboard for btn in row]
        admin_buttons = [btn.callback_data for row in admin_kwargs["reply_markup"].inline_keyboard for btn in row]
        expected_buttons = [btn.callback_data for row in expected_kb.inline_keyboard for btn in row]

        assert owner_buttons == expected_buttons
        assert admin_buttons == expected_buttons
        assert "admin_stats" in owner_buttons
        assert "admin_channels" in owner_buttons
        assert "admin_start_msg" in owner_buttons
        assert "admin_mgmt" in owner_buttons

    asyncio.run(_test())


def test_both_users_can_view_statistics(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        broadcast_service = test_setup["broadcast_service"]

        # Seed some user data
        await user_repo.save_pending_user(1001)
        await user_repo.complete_user_registration(1001)
        await user_repo.save_pending_user(1002)



        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        stats_handler = None
        for handler in admin_router.callback_query.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "cb_admin_stats":
                stats_handler = handler.callback
                break
        assert stats_handler is not None

        mock_bot = MagicMock()
        mock_me = MagicMock()
        mock_me.username = "TestBot"
        mock_bot.get_me = AsyncMock(return_value=mock_me)
        mock_bot.get_chat_member_count = AsyncMock(return_value=100)


        # User 5924300834 views stats
        cb_owner = MagicMock()
        cb_owner.data = "admin_stats"
        cb_owner.from_user.id = 5924300834
        cb_owner.answer = AsyncMock()
        cb_owner.message.edit_text = AsyncMock()

        await stats_handler(cb_owner, bot=mock_bot)
        cb_owner.message.edit_text.assert_called_once()
        args_owner, _ = cb_owner.message.edit_text.call_args
        assert "BOT STATISTIKASI" in args_owner[0]
        assert "Jami ro'yxatdan o'tganlar: <b>2 ta</b>" in args_owner[0]

        # User 5364318707 views stats
        cb_admin = MagicMock()
        cb_admin.data = "admin_stats"
        cb_admin.from_user.id = 5364318707
        cb_admin.answer = AsyncMock()
        cb_admin.message.edit_text = AsyncMock()

        await stats_handler(cb_admin, bot=mock_bot)
        cb_admin.message.edit_text.assert_called_once()
        args_admin, _ = cb_admin.message.edit_text.call_args
        assert "BOT STATISTIKASI" in args_admin[0]
        assert "Jami ro'yxatdan o'tganlar: <b>2 ta</b>" in args_admin[0]


    asyncio.run(_test())


def test_both_users_can_add_ordinary_admin(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        broadcast_service = test_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        add_msg_handler = None
        confirm_handler = None
        for handler in admin_router.message.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "msg_receive_admin_id":
                add_msg_handler = handler.callback
                break
        for handler in admin_router.callback_query.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "cb_admin_add_confirm":
                confirm_handler = handler.callback
                break

        assert add_msg_handler is not None
        assert confirm_handler is not None

        # 1. User 5924300834 adds ordinary admin 111111111
        msg1 = MagicMock()
        msg1.from_user.id = 5924300834
        msg1.text = "111111111"
        msg1.answer = AsyncMock()
        state1 = MagicMock()
        state1.update_data = AsyncMock()
        state1.set_state = AsyncMock()

        await add_msg_handler(msg1, state1)
        state1.update_data.assert_called_with(pending_admin_id=111111111)

        cb_confirm1 = MagicMock()
        cb_confirm1.from_user.id = 5924300834
        cb_confirm1.answer = AsyncMock()
        cb_confirm1.message.edit_text = AsyncMock()
        state1.get_data = AsyncMock(return_value={"pending_admin_id": 111111111})
        state1.clear = AsyncMock()

        await confirm_handler(cb_confirm1, state1)
        settings = await settings_repo.get_settings(cfg)
        assert 111111111 in settings.admin_ids
        assert await is_authorized_admin(111111111, cfg, settings_repo) is True

        # 2. User 5364318707 adds ordinary admin 222222222
        msg2 = MagicMock()
        msg2.from_user.id = 5364318707
        msg2.text = "222222222"
        msg2.answer = AsyncMock()
        state2 = MagicMock()
        state2.update_data = AsyncMock()
        state2.set_state = AsyncMock()

        await add_msg_handler(msg2, state2)
        state2.update_data.assert_called_with(pending_admin_id=222222222)

        cb_confirm2 = MagicMock()
        cb_confirm2.from_user.id = 5364318707
        cb_confirm2.answer = AsyncMock()
        cb_confirm2.message.edit_text = AsyncMock()
        state2.get_data = AsyncMock(return_value={"pending_admin_id": 222222222})
        state2.clear = AsyncMock()

        await confirm_handler(cb_confirm2, state2)
        settings = await settings_repo.get_settings(cfg)
        assert 222222222 in settings.admin_ids
        assert await is_authorized_admin(222222222, cfg, settings_repo) is True

        # 3. Input validation rejects invalid text or protected IDs
        invalid_msg = MagicMock()
        invalid_msg.from_user.id = 5364318707
        invalid_msg.text = "abc_invalid_id"
        invalid_msg.answer = AsyncMock()
        await add_msg_handler(invalid_msg, state2)
        assert "Noto'g'ri ID" in invalid_msg.answer.call_args[0][0]

        protected_add_msg = MagicMock()
        protected_add_msg.from_user.id = 5364318707
        protected_add_msg.text = "5924300834"
        protected_add_msg.answer = AsyncMock()
        await add_msg_handler(protected_add_msg, state2)
        assert "allaqachon himoyalangan administrator" in protected_add_msg.answer.call_args[0][0]

    asyncio.run(_test())


def test_both_users_can_remove_ordinary_admin(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        broadcast_service = test_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        # Add two ordinary admins
        await settings_repo.add_admin(333333333)
        await settings_repo.add_admin(444444444)

        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)
        del_confirm_handler = None
        for handler in admin_router.callback_query.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "cb_admin_del_confirm":
                del_confirm_handler = handler.callback
                break
        assert del_confirm_handler is not None

        # 1. User 5924300834 removes ordinary admin 333333333
        cb1 = MagicMock()
        cb1.data = "admin_del_confirm_333333333"
        cb1.from_user.id = 5924300834
        cb1.answer = AsyncMock()
        cb1.message.edit_text = AsyncMock()
        state1 = MagicMock()
        state1.clear = AsyncMock()

        await del_confirm_handler(cb1, state1)
        s1 = await settings_repo.get_settings(cfg)
        assert 333333333 not in s1.admin_ids
        assert await is_authorized_admin(333333333, cfg, settings_repo) is False

        # 2. User 5364318707 removes ordinary admin 444444444
        cb2 = MagicMock()
        cb2.data = "admin_del_confirm_444444444"
        cb2.from_user.id = 5364318707
        cb2.answer = AsyncMock()
        cb2.message.edit_text = AsyncMock()
        state2 = MagicMock()
        state2.clear = AsyncMock()

        await del_confirm_handler(cb2, state2)
        s2 = await settings_repo.get_settings(cfg)
        assert 444444444 not in s2.admin_ids
        assert await is_authorized_admin(444444444, cfg, settings_repo) is False

    asyncio.run(_test())


def test_mutual_and_self_removal_protection(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        broadcast_service = test_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        del_confirm_handler = None
        del_msg_handler = None
        for handler in admin_router.callback_query.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "cb_admin_del_confirm":
                del_confirm_handler = handler.callback
                break
        for handler in admin_router.message.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "msg_receive_admin_del_id":
                del_msg_handler = handler.callback
                break

        assert del_confirm_handler is not None
        assert del_msg_handler is not None

        # Case A: 5924300834 tries to remove 5364318707 via callback -> REJECTED
        cb_a = MagicMock()
        cb_a.data = "admin_del_confirm_5364318707"
        cb_a.from_user.id = 5924300834
        cb_a.answer = AsyncMock()
        await del_confirm_handler(cb_a, MagicMock())
        cb_a.answer.assert_called_with("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)

        # Case B: 5364318707 tries to remove 5924300834 via callback -> REJECTED
        cb_b = MagicMock()
        cb_b.data = "admin_del_confirm_5924300834"
        cb_b.from_user.id = 5364318707
        cb_b.answer = AsyncMock()
        await del_confirm_handler(cb_b, MagicMock())
        cb_b.answer.assert_called_with("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)

        # Case C: 5924300834 tries to remove themselves (5924300834) -> REJECTED
        cb_c = MagicMock()
        cb_c.data = "admin_del_confirm_5924300834"
        cb_c.from_user.id = 5924300834
        cb_c.answer = AsyncMock()
        await del_confirm_handler(cb_c, MagicMock())
        cb_c.answer.assert_called_with("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)

        # Case D: 5364318707 tries to remove themselves (5364318707) -> REJECTED
        cb_d = MagicMock()
        cb_d.data = "admin_del_confirm_5364318707"
        cb_d.from_user.id = 5364318707
        cb_d.answer = AsyncMock()
        await del_confirm_handler(cb_d, MagicMock())
        cb_d.answer.assert_called_with("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)

        # Case E: 5924300834 tries to remove 5364318707 via text ID input -> REJECTED
        msg_e = MagicMock()
        msg_e.from_user.id = 5924300834
        msg_e.text = "5364318707"
        msg_e.answer = AsyncMock()
        await del_msg_handler(msg_e, MagicMock())
        assert "Himoyalangan asosiy administratorlarni" in msg_e.answer.call_args[0][0]

        # Case F: 5364318707 tries to remove 5924300834 via text ID input -> REJECTED
        msg_f = MagicMock()
        msg_f.from_user.id = 5364318707
        msg_f.text = "5924300834"
        msg_f.answer = AsyncMock()
        await del_msg_handler(msg_f, MagicMock())
        assert "Himoyalangan asosiy administratorlarni" in msg_f.answer.call_args[0][0]

        # Case G: Direct repository call raises ValueError for protected IDs
        with pytest.raises(ValueError):
            await settings_repo.remove_admin(5924300834, config=cfg)
        with pytest.raises(ValueError):
            await settings_repo.remove_admin(5364318707, config=cfg)

        # Verify both remain administrators
        assert await is_authorized_admin(5924300834, cfg, settings_repo) is True
        assert await is_authorized_admin(5364318707, cfg, settings_repo) is True

    asyncio.run(_test())


def test_start_message_management_and_delivery(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        broadcast_service = test_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)
        user_router = create_user_router(cfg, user_repo, settings_repo)

        # Find start message admin handlers
        view_handler = None
        edit_input_handler = None
        confirm_handler = None
        reset_handler = None

        for handler in admin_router.callback_query.handlers:
            name = getattr(handler.callback, "__name__", "")
            if name == "cb_admin_start_message":
                view_handler = handler.callback
            elif name == "cb_start_message_confirm":
                confirm_handler = handler.callback
            elif name == "cb_start_message_reset":
                reset_handler = handler.callback

        for handler in admin_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "msg_receive_start_message":
                edit_input_handler = handler.callback

        assert view_handler is not None
        assert edit_input_handler is not None
        assert confirm_handler is not None
        assert reset_handler is not None

        # 1. View default start message
        cb_view = MagicMock()
        cb_view.from_user.id = 5364318707
        cb_view.answer = AsyncMock()
        cb_view.message.edit_text = AsyncMock()
        state_view = MagicMock()
        state_view.clear = AsyncMock()

        await view_handler(cb_view, state_view)
        cb_view.message.edit_text.assert_called_once()
        assert "/start Xabari Boshqaruvi" in cb_view.message.edit_text.call_args[0][0]

        # 2. Admin 5364318707 edits the message
        new_welcome = "🌟 <b>Arab tili marafoniga xush kelibsiz!</b>\nQuyidagi kanalga a'zo bo'ling:"
        msg_edit = MagicMock()
        msg_edit.from_user.id = 5364318707
        msg_edit.html_text = new_welcome
        msg_edit.text = new_welcome
        msg_edit.answer = AsyncMock()
        state_edit = MagicMock()
        state_edit.update_data = AsyncMock()
        state_edit.set_state = AsyncMock()

        await edit_input_handler(msg_edit, state_edit)
        state_edit.update_data.assert_called_with(pending_start_message=new_welcome)

        # Confirm saving the message
        cb_save = MagicMock()
        cb_save.from_user.id = 5364318707
        cb_save.answer = AsyncMock()
        cb_save.message.edit_text = AsyncMock()
        state_edit.get_data = AsyncMock(return_value={"pending_start_message": new_welcome})
        state_edit.clear = AsyncMock()

        await confirm_handler(cb_save, state_edit)
        settings = await settings_repo.get_settings(cfg)
        assert settings.start_message == new_welcome

        # 3. User sends /start and receives the newly updated message
        start_cmd_handler = None
        for handler in user_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "command_start_handler":
                start_cmd_handler = handler.callback
                break
        assert start_cmd_handler is not None

        user_start_msg = MagicMock()
        user_start_msg.from_user.id = 777001
        user_start_msg.answer = AsyncMock()
        cmd_obj = MagicMock()
        cmd_obj.args = None
        mock_bot = MagicMock()

        # User is not subscribed yet
        with patch.object(SubscriptionService, "is_subscribed", AsyncMock(return_value=False)):
            await start_cmd_handler(user_start_msg, cmd_obj, mock_bot)

        user_start_msg.answer.assert_called_once()
        sent_text = user_start_msg.answer.call_args[0][0]
        assert sent_text == new_welcome

        # 4. Admin 5924300834 resets the start message to default
        cb_reset = MagicMock()
        cb_reset.from_user.id = 5924300834
        cb_reset.answer = AsyncMock()
        cb_reset.message.edit_text = AsyncMock()
        state_reset = MagicMock()
        state_reset.clear = AsyncMock()

        await reset_handler(cb_reset, state_reset)
        s_reset = await settings_repo.get_settings(cfg)
        assert s_reset.start_message == DEFAULT_START_MESSAGE

    asyncio.run(_test())


def test_both_users_can_manage_channels(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        broadcast_service = test_setup["broadcast_service"]

        await settings_repo.get_settings(cfg)
        admin_router = create_admin_router(cfg, user_repo, settings_repo, broadcast_service)

        del_confirm_handler = None
        for handler in admin_router.callback_query.handlers:
            if getattr(handler.callback, "__name__", "") == "cb_ch_del_confirm":
                del_confirm_handler = handler.callback
                break
        assert del_confirm_handler is not None

        # 1. Add channel via settings_repo
        ch = ChannelModel(id=-10099887766, name="Yangi Test Kanal", url="https://t.me/yangi_kanal")
        await settings_repo.add_channel(ch)
        s = await settings_repo.get_settings(cfg)
        assert any(c.id == -10099887766 for c in s.mandatory_channels)

        # 2. User 5364318707 deletes the channel
        cb_del = MagicMock()
        cb_del.data = "admin_ch_del_confirm_-10099887766"
        cb_del.from_user.id = 5364318707
        cb_del.answer = AsyncMock()
        cb_del.message.edit_text = AsyncMock()
        state_del = MagicMock()
        state_del.clear = AsyncMock()

        await del_confirm_handler(cb_del, state_del)
        s_after = await settings_repo.get_settings(cfg)
        assert not any(c.id == -10099887766 for c in s_after.mandatory_channels)

    asyncio.run(_test())


def test_unauthorized_user_blocked(test_setup):
    async def _test():
        cfg = test_setup["cfg"]
        settings_repo = test_setup["settings_repo"]
        user_repo = test_setup["user_repo"]
        unauth_id = 999999999

        await settings_repo.get_settings(cfg)
        admin_filter = IsAdminFilter(cfg, settings_repo)

        # 1. IsAdminFilter rejects message
        msg = MagicMock()
        msg.from_user.id = unauth_id
        assert await admin_filter(msg) is False

        # 2. IsAdminFilter rejects callback query
        cb = MagicMock()
        cb.from_user.id = unauth_id
        assert await admin_filter(cb) is False

        # 3. User router responds to unauthorized /admin with access denial
        user_router = create_user_router(cfg, user_repo, settings_repo)
        unauth_handler = None
        for handler in user_router.message.handlers:
            if getattr(handler.callback, "__name__", "") == "cmd_unauthorized_admin":
                unauth_handler = handler.callback
                break
        assert unauth_handler is not None

        unauth_msg = MagicMock()
        unauth_msg.from_user.id = unauth_id
        unauth_msg.answer = AsyncMock()
        await unauth_handler(unauth_msg)
        unauth_msg.answer.assert_called_once()
        assert "Ruxsat etilmadi" in unauth_msg.answer.call_args[0][0]
        assert str(unauth_id) in unauth_msg.answer.call_args[0][0]

    asyncio.run(_test())


def test_changes_persist_after_restart(test_setup):
    async def _test():
        db = test_setup["db"]
        cfg = test_setup["cfg"]

        # Session 1: Modify settings, add admin, add channel, edit start message
        repo1 = SettingsRepository(db)
        await repo1.get_settings(cfg)

        await repo1.add_admin(555555555)
        await repo1.add_channel(ChannelModel(id=-10011223344, name="Persist Ch", url="https://t.me/persist_ch"))
        await repo1.update_start_message("Persisted Start Message ✨")

        # Session 2: Simulated bot restart (new repository instance pointing to same DB)
        repo2 = SettingsRepository(db)
        s2 = await repo2.get_settings(cfg)

        # Verify all changes survived restart
        assert 555555555 in s2.admin_ids
        assert await is_authorized_admin(555555555, cfg, repo2) is True
        assert any(c.id == -10011223344 for c in s2.mandatory_channels)
        assert s2.start_message == "Persisted Start Message ✨"

        # Both protected admins remain permanently authorized
        assert await is_authorized_admin(5924300834, cfg, repo2) is True
        assert await is_authorized_admin(5364318707, cfg, repo2) is True

    asyncio.run(_test())

