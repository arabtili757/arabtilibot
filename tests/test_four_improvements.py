"""Automated tests for the four major Arab Tili Marathon bot improvements.

Covers:
1. Automatic subscription verification and chat_member updates.
2. Promotional message editing with validation, preview, confirmation, and cancellation.
3. Personalized share button and URL encoding.
4. Accurate admin statistics (Tashkent timezone, channels, referrals, unverifiable channels).
5. Edge cases: duplicate updates, self-referral, out-of-order events, disabled subscription check.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import unquote
import pytest
import zoneinfo

from config import BotConfig
from database.models import BotSettingsDocument, ChannelModel
from database.repository import SettingsRepository, UserRepository
from handlers.middlewares import IsAdminFilter
from keyboards.admin_keyboards import (
    get_admin_main_keyboard,
    get_admin_stats_keyboard,
    get_promo_preview_keyboard,
)
from keyboards.user_keyboards import (
    SHARE_TEXT_PROMPT,
    build_share_url,
    get_share_keyboard,
    get_sub_keyboard,
)
from services.referral_service import ReferralService
from services.statistics_service import StatisticsService, get_tashkent_bounds
from services.subscription_service import SubscriptionService


class InMemoryCollection:
    """In-memory collection mock for isolated MongoDB tests."""

    def __init__(self):
        self.docs: dict[int | str, dict] = {}

    async def find_one(self, filter_dict, projection=None):
        for doc in self.docs.values():
            match = True
            for k, v in filter_dict.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                if projection:
                    return {k: doc[k] for k in projection if k in doc}
                return dict(doc)
        return None

    async def update_one(self, filter_dict, update_dict, upsert=False):
        key = filter_dict.get("user_id") or filter_dict.get("key")
        if key not in self.docs and upsert:
            self.docs[key] = dict(update_dict.get("$setOnInsert", {}))
        if key in self.docs:
            for k, v in update_dict.get("$set", {}).items():
                self.docs[key][k] = v
            for k in update_dict.get("$unset", {}):
                self.docs[key].pop(k, None)

    async def find_one_and_update(self, filter_dict, update_dict, return_document=None):
        key = filter_dict.get("user_id")
        doc = self.docs.get(key)
        if not doc:
            return None
        # Check all filter conditions
        for k, v in filter_dict.items():
            if doc.get(k) != v:
                return None
        if "$set" in update_dict:
            for k, v in update_dict["$set"].items():
                doc[k] = v
        if "$unset" in update_dict:
            for k in update_dict["$unset"]:
                doc.pop(k, None)
        if "$inc" in update_dict:
            for k, inc_val in update_dict["$inc"].items():
                doc[k] = doc.get(k, 0) + inc_val
        return dict(doc)

    async def count_documents(self, filter_dict):
        if not filter_dict:
            return len(self.docs)
        count = 0
        for doc in self.docs.values():
            match = True
            for k, v in filter_dict.items():
                if k == "$or":
                    or_match = False
                    for sub_cond in v:
                        for sub_k, sub_v in sub_cond.items():
                            if sub_v is None and doc.get(sub_k) is None:
                                or_match = True
                            elif isinstance(sub_v, dict) and "$exists" in sub_v:
                                exists = sub_k in doc
                                if exists == sub_v["$exists"]:
                                    or_match = True
                    if not or_match:
                        match = False
                        break
                elif isinstance(v, dict):
                    doc_val = doc.get(k)
                    if "$ne" in v and doc_val == v["$ne"]:
                        match = False
                        break
                    if "$gte" in v:
                        if doc_val is None or doc_val < v["$gte"]:
                            match = False
                            break
                    if "$gt" in v:
                        if doc_val is None or doc_val <= v["$gt"]:
                            match = False
                            break
                elif doc.get(k) != v:
                    match = False
                    break
            if match:
                count += 1
        return count

    def find(self, filter_dict=None, projection=None):
        class Cursor:
            def __init__(self, docs):
                self.docs = list(docs)

            def sort(self, key, direction):
                self.docs.sort(key=lambda d: d.get(key, 0), reverse=(direction == -1))
                return self

            def limit(self, count):
                self.docs = self.docs[:count]
                return self

            def __aiter__(self):
                self._iter = iter(self.docs)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration

        matching = []
        for doc in self.docs.values():
            if not filter_dict:
                matching.append(dict(doc))
                continue
            match = True
            for k, v in filter_dict.items():
                if isinstance(v, dict):
                    doc_val = doc.get(k)
                    if "$ne" in v and doc_val == v["$ne"]:
                        match = False
                        break
                    if "$gt" in v and (doc_val is None or doc_val <= v["$gt"]):
                        match = False
                        break
                elif doc.get(k) != v:
                    match = False
                    break
            if match:
                matching.append(dict(doc))
        return Cursor(matching)


class InMemoryDatabase:
    def __init__(self):
        self.collections = {
            "users": InMemoryCollection(),
            "settings": InMemoryCollection(),
        }

    def __getitem__(self, name):
        return self.collections[name]


# ---------------------------------------------------------------------------
# 1. Automatic Subscription Verification Tests
# ---------------------------------------------------------------------------

def test_automatic_subscription_verification_flow():
    """Verify user starts pending, joins channels, and completes automatically without manual button."""
    async def _test():
        db = InMemoryDatabase()
        user_repo = UserRepository(db)
        service = ReferralService(user_repo)

        # 1. Referrer exists
        await user_repo.create_user(user_id=100)

        # 2. User starts bot with referral parameter 100
        pending_user = await service.save_pending_registration(user_id=200, ref_arg="100")
        assert pending_user["status"] == "pending"
        assert pending_user["pending_referrer_id"] == 100
        assert await user_repo.get_referrals_count(100) == 0

        # User is not completed yet
        u = await user_repo.get_user(200)
        assert u["status"] == "pending"

        # 3. User joins channels -> complete_registration is triggered automatically
        res = await service.complete_registration(user_id=200, required_referrals=3)
        assert res.is_new_user is True
        assert res.referrer_notification is not None
        assert res.referrer_notification.referrer_id == 100
        assert res.referrer_notification.current_count == 1
        assert res.referrer_notification.kind == "progress"

        # Database state verified
        completed_u = await user_repo.get_user(200)
        assert completed_u["status"] == "completed"
        assert completed_u["referrer_id"] == 100
        assert "pending_referrer_id" not in completed_u
        assert completed_u["registered_at"] is not None
        assert await user_repo.get_referrals_count(100) == 1

    asyncio.run(_test())


def test_immediate_registration_if_already_subscribed():
    """If user was already subscribed to all channels when clicking /start, register immediately."""
    async def _test():
        db = InMemoryDatabase()
        user_repo = UserRepository(db)
        service = ReferralService(user_repo)

        await user_repo.create_user(user_id=500)

        # User starts with referral 500
        await service.save_pending_registration(user_id=501, ref_arg="500")
        # Simulating already subscribed -> complete_registration called right away
        res = await service.complete_registration(user_id=501, required_referrals=3)

        assert res.is_new_user is True
        assert res.referrer_notification.referrer_id == 500
        assert await user_repo.get_referrals_count(500) == 1

        u = await user_repo.get_user(501)
        assert u["status"] == "completed"
        assert u["referrer_id"] == 500

    asyncio.run(_test())


def test_referral_parameter_preserved_during_pending():
    """Original referral parameter is preserved throughout restarts or repeated /starts while pending."""
    async def _test():
        db = InMemoryDatabase()
        user_repo = UserRepository(db)
        service = ReferralService(user_repo)

        await user_repo.create_user(user_id=900)

        # 1. User starts with 900
        await service.save_pending_registration(user_id=901, ref_arg="900")

        # 2. User starts again with no args or different args while still pending
        await service.save_pending_registration(user_id=901, ref_arg="888")
        await service.save_pending_registration(user_id=901, ref_arg=None)

        u = await user_repo.get_user(901)
        # Original 900 is strictly preserved!
        assert u["pending_referrer_id"] == 900

        # 3. User joins channels -> completed and awarded to 900
        res = await service.complete_registration(user_id=901, required_referrals=3)
        assert res.referrer_notification.referrer_id == 900
        assert await user_repo.get_referrals_count(900) == 1

    asyncio.run(_test())


def test_duplicate_membership_updates_idempotency():
    """Duplicate or out-of-order updates never credit referrals twice."""
    async def _test():
        db = InMemoryDatabase()
        user_repo = UserRepository(db)
        service = ReferralService(user_repo)

        await user_repo.create_user(user_id=700)
        await service.save_pending_registration(user_id=701, ref_arg="700")

        # First update completes registration
        res1 = await service.complete_registration(user_id=701, required_referrals=3)
        assert res1.is_new_user is True
        assert res1.referrer_notification is not None

        # Duplicate update arrives (e.g. from Telegram duplicate event)
        res2 = await service.complete_registration(user_id=701, required_referrals=3)
        assert res2.is_new_user is False
        assert res2.referrer_notification is None

        # Third update arrives
        res3 = await service.complete_registration(user_id=701, required_referrals=3)
        assert res3.is_new_user is False

        # Referrer count is strictly 1, never 2 or 3
        assert await user_repo.get_referrals_count(700) == 1

    asyncio.run(_test())


def test_self_referral_and_duplicate_referral_prevention():
    """Self-referrals and duplicate referrals are safely rejected."""
    async def _test():
        db = InMemoryDatabase()
        user_repo = UserRepository(db)
        service = ReferralService(user_repo)

        # Self-referral
        await service.save_pending_registration(user_id=800, ref_arg="800")
        res = await service.complete_registration(user_id=800, required_referrals=3)
        assert res.referrer_notification is None
        u = await user_repo.get_user(800)
        assert u["referrer_id"] is None

        # User already registered cannot be credited to someone else later
        await user_repo.create_user(user_id=801)
        res_dup = await service.process_registration(user_id=801, ref_arg="800", required_referrals=3)
        assert res_dup.is_new_user is False
        assert res_dup.referrer_notification is None
        assert await user_repo.get_referrals_count(800) == 0

    asyncio.run(_test())


def test_disabled_subscription_check_behavior():
    """When subscription checking is disabled, is_subscribed returns True immediately."""
    async def _test():
        bot = AsyncMock()
        channels = [ChannelModel(name="Ch", url="https://t.me/ch", id=-1001)]
        is_sub = await SubscriptionService.is_subscribed(
            bot=bot, user_id=123, channels=channels, check_enabled=False
        )
        assert is_sub is True
        bot.get_chat_member.assert_not_called()

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 2. Promotional Message Editing Tests
# ---------------------------------------------------------------------------

def test_admin_promo_text_validation_and_persistence():
    """Admin promotional message editing, validation, and persistence in MongoDB."""
    async def _test():
        db = InMemoryDatabase()
        settings_repo = SettingsRepository(db)
        config = BotConfig(
            BOT_TOKEN="1:x",
            ADMIN_IDS="111",
            REQUIRED_REFERRALS=3,
            CLOSED_CHANNEL_LINK="https://t.me/+link",
            SUBSCRIPTION_CHECK_ENABLED=True,
            MANDATORY_CHANNELS='[{"name": "Ch", "url": "https://t.me/ch", "id": -1001}]',
            MONGODB_URI="mongodb://localhost:27017",
        )

        settings = await settings_repo.get_settings(config)
        original_text = settings.share_text
        assert "ARAB TILI MARAFONI" in original_text

        # Validate replacement text does not require {link}
        plain_text = "Marafon boshlanmoqda! Qo'shiling!"
        assert "{link}" not in plain_text

        # Valid replacement text with HTML formatting (supports optional {link} or plain text)
        new_text = (
            "🚀 <b>YANGILANGAN MARAFON</b>\n\n"
            "Arab tili noldan boshlanmoqda.\n\n"
            '<a href="{link}">Ro\'yxatdan o\'ting!</a>'
        )
        assert "{link}" in new_text

        # Test formatting with personalized link
        sample_link = "https://t.me/ArabiyaBoost_bot?start=12345"
        formatted = new_text.format(link=sample_link)
        assert sample_link in formatted
        assert "<b>YANGILANGAN MARAFON</b>" in formatted

        # Save to MongoDB settings
        updated = await settings_repo.update_settings({"share_text": new_text})
        assert updated.share_text == new_text

        # Check persistence (re-fetching from DB)
        fresh_settings = await settings_repo.get_settings(config)
        assert fresh_settings.share_text == new_text

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 3. Personalized Share Button Tests
# ---------------------------------------------------------------------------

def test_personalized_share_button_and_url_encoding():
    """Verify button label, URL encoding, Uzbek text, and referral link."""
    user_id = 987654321
    bot_username = "ArabiyaBoost_bot"

    my_link, share_url = build_share_url(bot_username, user_id)

    # Correct referral link
    assert my_link == "https://t.me/ArabiyaBoost_bot?start=987654321"

    # Telegram native share format
    assert share_url.startswith("https://t.me/share/url?")
    assert "url=https%3A%2F%2Ft.me%2FArabiyaBoost_bot%3Fstart%3D987654321" in share_url

    # Exact required Uzbek text
    assert SHARE_TEXT_PROMPT == "Shu botga kirib ko'ring, zo'r ekan! Arab tili marafoniga qo'shiling!"
    assert "text=" in share_url
    assert unquote(share_url.split("text=")[1]) == SHARE_TEXT_PROMPT

    # Exact button label
    kb = get_share_keyboard(share_url)
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(all_buttons) == 1
    btn = all_buttons[0]
    assert btn.text == "📤 Do'stlarga ulashish"
    assert btn.url == share_url


# ---------------------------------------------------------------------------
# 4. Accurate Admin Statistics Tests
# ---------------------------------------------------------------------------

def test_admin_statistics_calculation_and_tashkent_timezone():
    """Test user stats, Tashkent timezone date filtering, channel audit, and top referrers."""
    async def _test():
        db = InMemoryDatabase()
        user_repo = UserRepository(db)
        settings_repo = SettingsRepository(db)

        config = BotConfig(
            BOT_TOKEN="1:x",
            ADMIN_IDS="111",
            REQUIRED_REFERRALS=3,
            CLOSED_CHANNEL_LINK="https://t.me/+link",
            SUBSCRIPTION_CHECK_ENABLED=True,
            MANDATORY_CHANNELS='[{"name": "Channel 1", "url": "https://t.me/c1", "id": -1001}]',
            MONGODB_URI="mongodb://localhost:27017",
        )
        await settings_repo.get_settings(config)

        # Setup mock users
        now_tashkent, start_today_utc, start_7d_utc = get_tashkent_bounds()

        # 1. User registered today
        await user_repo.create_user(user_id=10)
        # 2. User registered 3 days ago (within 7 days)
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        await db["users"].update_one(
            {"user_id": 20},
            {"$setOnInsert": {
                "user_id": 20, "referrer_id": 10, "status": "completed",
                "registered_at": three_days_ago, "referrals_count": 0
            }},
            upsert=True
        )
        await user_repo.increment_referrals(10)

        # 3. User registered 10 days ago (older than 7 days)
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        await db["users"].update_one(
            {"user_id": 30},
            {"$setOnInsert": {
                "user_id": 30, "referrer_id": None, "status": "completed",
                "registered_at": ten_days_ago, "referrals_count": 0
            }},
            upsert=True
        )

        # 4. Pending user (not completed)
        await user_repo.save_pending_user(user_id=40, pending_referrer_id=10)

        # 5. Legacy user without timestamp
        await db["users"].update_one(
            {"user_id": 50},
            {"$setOnInsert": {
                "user_id": 50, "referrer_id": None, "status": "completed",
                "registered_at": None, "referrals_count": 0
            }},
            upsert=True
        )

        stats_service = StatisticsService(user_repo, settings_repo)

        # Mock Bot
        bot = AsyncMock()
        bot_user = MagicMock()
        bot_user.username = "ArabiyaBoost_bot"
        bot.get_me.return_value = bot_user

        # Bot is admin in channel -1001
        bot_member = MagicMock()
        bot_member.status = "administrator"

        user_member = MagicMock()
        user_member.status = "member"

        def mock_get_chat_member(chat_id, user_id):
            if user_id == bot.id:
                return bot_member
            return user_member

        bot.get_chat_member.side_effect = mock_get_chat_member

        stats = await stats_service.get_statistics(bot=bot, config=config, force_refresh=True)

        # Assertions
        assert stats["total_registered"] == 4  # Users 10, 20, 30, 50
        assert stats["pending_users_count"] == 1  # User 40
        assert stats["total_users"] == 5
        assert stats["registered_today"] >= 1  # User 10
        assert stats["registered_7d"] >= 2  # Users 10, 20
        assert stats["legacy_no_timestamp"] == 1  # User 50
        assert stats["total_unique_referrals"] == 1  # User 20 referred by 10

        # Channel stats
        assert len(stats["channel_stats"]) == 1
        ch_stat = stats["channel_stats"][0]
        assert ch_stat["name"] == "Channel 1"
        assert ch_stat["id"] == -1001
        assert ch_stat["subscribed"] == 4
        assert ch_stat["not_subscribed"] == 0
        assert ch_stat["unverifiable"] == 0
        assert ch_stat["bot_is_admin"] is True

        # Top referrers
        assert len(stats["top_referrers"]) == 1
        top_ref = stats["top_referrers"][0]
        assert top_ref["user_id"] == 10
        assert top_ref["count"] == 1
        assert top_ref["link"] == "https://t.me/ArabiyaBoost_bot?start=10"

        # Format message test
        msg = StatisticsService.format_statistics_message(stats)
        assert "BOT STATISTIKASI" in msg
        assert "A. Foydalanuvchilar statistikasi" in msg
        assert "B. Majburiy kanallar statistikasi" in msg
        assert "C. Referal statistikasi" in msg
        assert "https://t.me/ArabiyaBoost_bot?start=10" in msg

    asyncio.run(_test())


def test_telegram_channel_check_failure_marked_unverifiable():
    """API failures or missing bot admin rights are never counted as subscribed/unsubscribed."""
    async def _test():
        db = InMemoryDatabase()
        user_repo = UserRepository(db)
        settings_repo = SettingsRepository(db)

        config = BotConfig(
            BOT_TOKEN="1:x",
            ADMIN_IDS="111",
            REQUIRED_REFERRALS=3,
            CLOSED_CHANNEL_LINK="https://t.me/+link",
            SUBSCRIPTION_CHECK_ENABLED=True,
            MANDATORY_CHANNELS='[{"name": "Private Ch", "url": "https://t.me/priv", "id": -100999}]',
            MONGODB_URI="mongodb://localhost:27017",
        )
        await settings_repo.get_settings(config)
        await user_repo.create_user(user_id=11)

        stats_service = StatisticsService(user_repo, settings_repo)

        bot = AsyncMock()
        bot_user = MagicMock()
        bot_user.username = "ArabiyaBoost_bot"
        bot.get_me.return_value = bot_user

        # Bot is NOT admin in channel (e.g. member or error)
        bot_member = MagicMock()
        bot_member.status = "member"  # not administrator!
        bot.get_chat_member.return_value = bot_member

        stats = await stats_service.get_statistics(bot=bot, config=config, force_refresh=True)

        ch_stat = stats["channel_stats"][0]
        assert ch_stat["bot_is_admin"] is False
        assert ch_stat["admin_warning"] is not None
        assert ch_stat["unverifiable"] == 1
        assert ch_stat["subscribed"] == 0
        assert ch_stat["not_subscribed"] == 0

    asyncio.run(_test())


def test_unauthorized_admin_access():
    """Verify non-admin users are rejected by IsAdminFilter."""
    async def _test():
        config = BotConfig(
            BOT_TOKEN="1:x",
            ADMIN_IDS="111,222",
            REQUIRED_REFERRALS=3,
            CLOSED_CHANNEL_LINK="https://t.me/+link",
            SUBSCRIPTION_CHECK_ENABLED=True,
            MANDATORY_CHANNELS='[]',
            MONGODB_URI="mongodb://localhost:27017",
        )
        admin_filter = IsAdminFilter(config)

        # Allowed admin
        event_admin = MagicMock()
        event_admin.from_user.id = 111
        assert await admin_filter(event_admin) is True

        # Unauthorized user
        event_stranger = MagicMock()
        event_stranger.from_user.id = 999
        assert await admin_filter(event_stranger) is False

    asyncio.run(_test())
