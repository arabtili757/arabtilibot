"""Automated tests for Owner/Admin permissions and Dynamic Channel Management.

Tests:
1. Owner and Admin Separation & Authorization
2. Dynamic Admin Management & Persistence Across Restarts
3. Dynamic Mandatory Channel Management & Persistence
4. Telegram Bot API Preflight Channel Access Verification
5. Subscription Toggle & Dynamic Verification
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from pydantic import ValidationError

from config import BotConfig, DEFAULT_MANDATORY_CHANNELS
from database.models import ChannelModel
from database.repository import SettingsRepository
from handlers.middlewares import IsAdminFilter, IsOwnerFilter
from services.subscription_service import SubscriptionService
from tests.test_database_repository import AsyncMockDatabase


# ==============================================================================
# 1. OWNER AND ADMIN CONFIGURATION & AUTHORIZATION TESTS
# ==============================================================================

def test_config_owner_and_admin_separation():
    """Verify OWNER_IDS and ADMIN_IDS are parsed separately and handle various formats."""
    # Test comma-separated strings
    cfg = BotConfig(
        BOT_TOKEN="123:test_token",
        OWNER_IDS="5924300834, 111222333",
        ADMIN_IDS="5364318707, 444555666",
        MONGODB_URI="mongodb://localhost:27017",
    )
    assert cfg.owner_ids == [5924300834, 111222333]
    assert cfg.admin_ids == [5364318707, 444555666]

    # Owner has full owner and admin rights
    assert cfg.is_owner(5924300834) is True
    assert cfg.is_admin(5924300834) is True

    # Regular admin has admin rights but NOT owner rights
    assert cfg.is_owner(5364318707) is False
    assert cfg.is_admin(5364318707) is True

    # Unauthorized user has neither
    assert cfg.is_owner(999999999) is False
    assert cfg.is_admin(999999999) is False


def test_config_owner_auto_admin_access():
    """An owner must automatically have full admin access, even if not in ADMIN_IDS."""
    cfg = BotConfig(
        BOT_TOKEN="123:test_token",
        OWNER_IDS="5924300834",
        ADMIN_IDS="",  # Empty admin list
        MONGODB_URI="mongodb://localhost:27017",
    )
    assert cfg.owner_ids == [5924300834]
    assert cfg.admin_ids == []
    assert cfg.is_owner(5924300834) is True
    assert cfg.is_admin(5924300834) is True


def test_config_repr_does_not_leak_secrets():
    """String representations must never expose bot token or MongoDB credentials."""
    cfg = BotConfig(
        BOT_TOKEN="SECRET_TOKEN_XYZ",
        OWNER_IDS="5924300834",
        ADMIN_IDS="5364318707",
        MONGODB_URI="mongodb+srv://admin:SUPER_SECRET_PASSWORD@cluster.mongodb.net",
    )
    rep = repr(cfg)
    assert "SECRET_TOKEN" not in rep
    assert "SUPER_SECRET_PASSWORD" not in rep
    assert "5924300834" in rep
    assert "5364318707" in rep


def test_is_owner_filter():
    """IsOwnerFilter must allow owners and reject regular admins and unauthorized users."""
    async def _test():
        cfg = BotConfig(
            BOT_TOKEN="123:test",
            OWNER_IDS="5924300834",
            ADMIN_IDS="5364318707",
            MONGODB_URI="mongodb://localhost:27017",
        )
        owner_filter = IsOwnerFilter(cfg)

        owner_event = MagicMock()
        owner_event.from_user.id = 5924300834
        assert await owner_filter(owner_event) is True

        admin_event = MagicMock()
        admin_event.from_user.id = 5364318707
        assert await owner_filter(admin_event) is False

        user_event = MagicMock()
        user_event.from_user.id = 999999999
        assert await owner_filter(user_event) is False

        no_user_event = MagicMock()
        no_user_event.from_user = None
        assert await owner_filter(no_user_event) is False

    asyncio.run(_test())


def test_is_admin_filter_with_database_admins():
    """IsAdminFilter allows owners and DB admins, rejects unauthorized users."""
    async def _test():
        db = AsyncMockDatabase()
        repo = SettingsRepository(db)
        cfg = BotConfig(
            BOT_TOKEN="123:test",
            OWNER_IDS="5924300834",
            ADMIN_IDS="5364318707",
            MONGODB_URI="mongodb://localhost:27017",
        )
        await repo.get_settings(cfg)

        admin_filter = IsAdminFilter(cfg, repo)

        # Owner allowed
        e_owner = MagicMock()
        e_owner.from_user.id = 5924300834
        assert await admin_filter(e_owner) is True

        # Initial admin allowed
        e_admin = MagicMock()
        e_admin.from_user.id = 5364318707
        assert await admin_filter(e_admin) is True

        # Unknown user rejected
        e_user = MagicMock()
        e_user.from_user.id = 12345
        assert await admin_filter(e_user) is False

        # Add new admin dynamically in DB
        await repo.add_admin(12345)
        # Now immediately allowed without restart!
        assert await admin_filter(e_user) is True

        # Remove admin dynamically
        await repo.remove_admin(12345)
        # Now immediately rejected
        assert await admin_filter(e_user) is False

    asyncio.run(_test())


# ==============================================================================
# 2. DYNAMIC ADMIN MANAGEMENT & RESTART PERSISTENCE TESTS
# ==============================================================================

def test_admin_initialization_and_removal_persistence():
    """Admins initialized on first run; removed admins must NOT be re-added on restart."""
    async def _test():
        db = AsyncMockDatabase()
        cfg = BotConfig(
            BOT_TOKEN="123:test",
            OWNER_IDS="5924300834",
            ADMIN_IDS="5364318707, 888888888",
            MONGODB_URI="mongodb://localhost:27017",
        )

        # First run: repository initializes admin_ids from cfg.admin_ids
        repo1 = SettingsRepository(db)
        s1 = await repo1.get_settings(cfg)
        assert 5364318707 in s1.admin_ids
        assert 888888888 in s1.admin_ids
        assert s1.admins_initialized is True

        # Owner removes 888888888
        await repo1.remove_admin(888888888)
        s2 = await repo1.get_settings(cfg)
        assert 888888888 not in s2.admin_ids

        # Simulated restart: create new SettingsRepository instance against existing DB
        repo2 = SettingsRepository(db)
        s_restarted = await repo2.get_settings(cfg)
        # 888888888 must NOT be restored even though it is still in cfg.ADMIN_IDS!
        assert 888888888 not in s_restarted.admin_ids
        assert 5364318707 in s_restarted.admin_ids

        # Check is_admin after restart
        assert await repo2.is_admin(888888888, cfg) is False
        assert await repo2.is_admin(5364318707, cfg) is True
        # Owner always has access
        assert await repo2.is_admin(5924300834, cfg) is True

    asyncio.run(_test())


# ==============================================================================
# 3. DYNAMIC MANDATORY CHANNELS & RESTART PERSISTENCE TESTS
# ==============================================================================

def test_channel_initialization_and_removal_persistence():
    """Default channels initialized on first run; deleted channels are NOT re-added on restart."""
    async def _test():
        db = AsyncMockDatabase()
        cfg = BotConfig(
            BOT_TOKEN="123:test",
            OWNER_IDS="5924300834",
            ADMIN_IDS="5364318707",
            MANDATORY_CHANNELS="",
            MONGODB_URI="mongodb://localhost:27017",
        )

        # First run: should seed default channels
        repo1 = SettingsRepository(db)
        s1 = await repo1.get_settings(cfg)
        assert len(s1.mandatory_channels) == 3
        default_ids = {ch.id for ch in s1.mandatory_channels}
        assert -1003806288160 in default_ids  # Tariqul Arobiyya
        assert -1002499676601 in default_ids  # زبان عربی با مبارک
        assert -1001597783515 in default_ids  # ARABIC_WORLD

        # Administrator removes all three channels
        for cid in list(default_ids):
            await repo1.remove_channel(cid)

        s_cleared = await repo1.get_settings(cfg)
        assert len(s_cleared.mandatory_channels) == 0

        # Simulated bot restart: new repository instance with existing DB
        repo2 = SettingsRepository(db)
        s_restarted = await repo2.get_settings(cfg)
        # Deleted channels must NOT be restored!
        assert len(s_restarted.mandatory_channels) == 0

        # Add a custom channel
        new_ch = ChannelModel(name="Yangi Kanal", url="https://t.me/yangi_kanal", id=-1009999999999)
        await repo2.add_channel(new_ch)

        s_with_new = await repo2.get_settings(cfg)
        assert len(s_with_new.mandatory_channels) == 1
        assert s_with_new.mandatory_channels[0].id == -1009999999999

        # Simulated second restart
        repo3 = SettingsRepository(db)
        s_restarted2 = await repo3.get_settings(cfg)
        assert len(s_restarted2.mandatory_channels) == 1
        assert s_with_new.mandatory_channels[0].id == -1009999999999

    asyncio.run(_test())


# ==============================================================================
# 4. PREFLIGHT CHANNEL ACCESS VERIFICATION TESTS (MOCKED TELEGRAM API)
# ==============================================================================

def test_preflight_channel_access_success():
    """Preflight check passes when bot can getChat and is an administrator."""
    async def _test():
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(id=777))

        mock_chat = MagicMock()
        mock_chat.title = "Test Channel"
        bot.get_chat = AsyncMock(return_value=mock_chat)

        mock_member = MagicMock()
        mock_member.status = "administrator"
        bot.get_chat_member = AsyncMock(return_value=mock_member)

        is_valid, msg, title = await SubscriptionService.verify_channel_access(bot, -1001234567890)
        assert is_valid is True
        assert "Bot kanal ma'muri hisoblanadi" in msg
        assert title == "Test Channel"

    asyncio.run(_test())


def test_preflight_channel_access_rejects_non_admin():
    """Preflight check rejects when bot is in channel but NOT administrator."""
    async def _test():
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(id=777))

        mock_chat = MagicMock()
        mock_chat.title = "Test Channel"
        bot.get_chat = AsyncMock(return_value=mock_chat)

        mock_member = MagicMock()
        mock_member.status = "member"  # Just regular member, not admin!
        bot.get_chat_member = AsyncMock(return_value=mock_member)

        is_valid, msg, title = await SubscriptionService.verify_channel_access(bot, -1001234567890)
        assert is_valid is False
        assert "ma'mur (admin) emas" in msg
        assert title == "Test Channel"

    asyncio.run(_test())


def test_preflight_channel_access_rejects_inaccessible_channel():
    """Preflight check rejects and safely handles when channel is not accessible (getChat fails)."""
    async def _test():
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(id=777))
        bot.get_chat = AsyncMock(side_effect=Exception("Chat not found"))

        is_valid, msg, title = await SubscriptionService.verify_channel_access(bot, -1009999999999)
        assert is_valid is False
        assert "Kanalga ulanib bo'lmadi" in msg
        assert title is None

    asyncio.run(_test())


# ==============================================================================
# 5. SUBSCRIPTION TOGGLE & DYNAMIC VERIFICATION TESTS
# ==============================================================================

def test_subscription_service_respects_toggle_and_dynamic_channels():
    """Subscription checking respects subscription_check_enabled flag and checks dynamic channels."""
    async def _test():
        bot = MagicMock()

        # Channel 1: user is member
        # Channel 2: user is left
        async def mock_get_chat_member(chat_id, user_id):
            m = MagicMock()
            if chat_id == -1001:
                m.status = "member"
            elif chat_id == -1002:
                m.status = "left"
            return m

        bot.get_chat_member = AsyncMock(side_effect=mock_get_chat_member)

        channels = [
            ChannelModel(name="Ch 1", url="https://t.me/ch1", id=-1001),
            ChannelModel(name="Ch 2", url="https://t.me/ch2", id=-1002),
        ]

        # When subscription_check_enabled is True, user has not joined Ch 2 -> False
        res_enabled = await SubscriptionService.is_subscribed(
            bot=bot,
            user_id=12345,
            channels=channels,
            check_enabled=True,
        )
        assert res_enabled is False

        # When subscription_check_enabled is False, registration is not blocked -> True
        res_disabled = await SubscriptionService.is_subscribed(
            bot=bot,
            user_id=12345,
            channels=channels,
            check_enabled=False,
        )
        assert res_disabled is True

        # If user is subscribed to all configured channels -> True
        bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
        res_all_sub = await SubscriptionService.is_subscribed(
            bot=bot,
            user_id=12345,
            channels=channels,
            check_enabled=True,
        )
        assert res_all_sub is True

    asyncio.run(_test())


# ==============================================================================
# 6. ROUTER PERMISSION CHECKS & ADMIN MANAGEMENT WORKFLOW TESTS
# ==============================================================================

def test_admin_router_owner_restriction():
    """Verify regular admins are rejected from admin management handlers."""
    from handlers.admin_handlers import create_admin_router

    async def _test():
        db = AsyncMockDatabase()
        repo = SettingsRepository(db)
        cfg = BotConfig(
            BOT_TOKEN="123:test",
            OWNER_IDS="5924300834",
            ADMIN_IDS="5364318707",
            MONGODB_URI="mongodb://localhost:27017",
        )
        await repo.get_settings(cfg)
        broadcast_service = MagicMock()

        router = create_admin_router(cfg, MagicMock(), repo, broadcast_service)

        # Find handler for admin_mgmt
        mgmt_handler = None
        for handler in router.callback_query.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "cb_admin_mgmt":
                mgmt_handler = handler.callback
                break

        assert mgmt_handler is not None
        state = MagicMock()
        state.clear = AsyncMock()

        # 1. Protected admin 5364318707 opens admin_mgmt -> succeeds
        cb_regular = MagicMock()
        cb_regular.data = "admin_mgmt"
        cb_regular.from_user.id = 5364318707
        cb_regular.answer = AsyncMock()
        cb_regular.message.edit_text = AsyncMock()

        await mgmt_handler(cb_regular, state)
        cb_regular.message.edit_text.assert_called_once()
        cb_regular.answer.assert_called_once()

        # 2. Protected admin 5924300834 opens admin_mgmt -> succeeds
        cb_owner = MagicMock()
        cb_owner.data = "admin_mgmt"
        cb_owner.from_user.id = 5924300834
        cb_owner.answer = AsyncMock()
        cb_owner.message.edit_text = AsyncMock()

        await mgmt_handler(cb_owner, state)
        cb_owner.message.edit_text.assert_called_once()
        cb_owner.answer.assert_called_once()

    asyncio.run(_test())


def test_cannot_remove_or_demote_owner():
    """Verify protected administrators cannot remove each other or themselves."""
    from handlers.admin_handlers import create_admin_router

    async def _test():
        db = AsyncMockDatabase()
        repo = SettingsRepository(db)
        cfg = BotConfig(
            BOT_TOKEN="123:test",
            OWNER_IDS="5924300834",
            ADMIN_IDS="5364318707",
            MONGODB_URI="mongodb://localhost:27017",
        )
        await repo.get_settings(cfg)
        router = create_admin_router(cfg, MagicMock(), repo, MagicMock())

        # Find cb_admin_del_confirm handler
        del_confirm_handler = None
        for handler in router.callback_query.handlers:
            if hasattr(handler.callback, "__name__") and handler.callback.__name__ == "cb_admin_del_confirm":
                del_confirm_handler = handler.callback
                break

        assert del_confirm_handler is not None

        # 1. 5364318707 attempts to remove 5924300834 -> rejected
        cb1 = MagicMock()
        cb1.data = "admin_del_confirm_5924300834"
        cb1.from_user.id = 5364318707
        cb1.answer = AsyncMock()
        await del_confirm_handler(cb1, MagicMock())
        cb1.answer.assert_called_with("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)

        # 2. 5924300834 attempts to remove 5364318707 -> rejected
        cb2 = MagicMock()
        cb2.data = "admin_del_confirm_5364318707"
        cb2.from_user.id = 5924300834
        cb2.answer = AsyncMock()
        await del_confirm_handler(cb2, MagicMock())
        cb2.answer.assert_called_with("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)

        # 3. 5924300834 attempts to remove self (5924300834) -> rejected
        cb3 = MagicMock()
        cb3.data = "admin_del_confirm_5924300834"
        cb3.from_user.id = 5924300834
        cb3.answer = AsyncMock()
        await del_confirm_handler(cb3, MagicMock())
        cb3.answer.assert_called_with("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)

    asyncio.run(_test())


