"""Unit tests for MongoDB UserRepository and SettingsRepository."""

import asyncio
from typing import Any, Dict, List
import pytest
from config import BotConfig
from database.models import ChannelModel
from database.repository import SettingsRepository, UserRepository


class AsyncMockCollection:
    """Async in-memory MongoDB collection mock for testing repositories."""

    def __init__(self):
        self.docs: Dict[Any, Dict[str, Any]] = {}

    async def find_one(self, filter_dict, projection=None):
        key = filter_dict.get("user_id") if "user_id" in filter_dict else filter_dict.get("key")
        doc = self.docs.get(key)
        if not doc:
            return None
        if projection:
            res = {}
            for k in projection:
                if k in doc:
                    res[k] = doc[k]
            if "_id" in projection:
                res["_id"] = "mock_id"
            return res
        return dict(doc)

    async def update_one(self, filter_dict, update_dict, upsert=False):
        key = filter_dict.get("user_id") if "user_id" in filter_dict else filter_dict.get("key")
        if key not in self.docs and upsert:
            self.docs[key] = dict(update_dict.get("$setOnInsert", {}))
        if key in self.docs:
            for k, v in update_dict.get("$set", {}).items():
                self.docs[key][k] = v

    async def find_one_and_update(self, filter_dict, update_dict, return_document=None):
        key = filter_dict.get("user_id")
        doc = self.docs.get(key)
        if not doc:
            return None
        if "$inc" in update_dict:
            for k, inc_val in update_dict["$inc"].items():
                doc[k] = doc.get(k, 0) + inc_val
        if "$set" in update_dict:
            for k, set_val in update_dict["$set"].items():
                doc[k] = set_val
        return dict(doc)

    async def count_documents(self, filter_dict):
        if not filter_dict:
            return len(self.docs)
        if "referrals_count" in filter_dict:
            gte = filter_dict["referrals_count"].get("$gte", 0)
            return sum(1 for d in self.docs.values() if d.get("referrals_count", 0) >= gte)
        return len(self.docs)

    def aggregate(self, pipeline):
        class AggCursor:
            def __init__(self, total):
                self.total = total

            async def to_list(self, length):
                return [{"total": self.total}]

        total = sum(d.get("referrals_count", 0) for d in self.docs.values())
        return AggCursor(total)

    def find(self, filter_dict=None, projection=None):
        class FindCursor:
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

        docs = list(self.docs.values())
        if filter_dict and "referrals_count" in filter_dict:
            gt = filter_dict["referrals_count"].get("$gt", 0)
            docs = [d for d in docs if d.get("referrals_count", 0) > gt]
        return FindCursor(docs)


class AsyncMockDatabase:
    def __init__(self):
        self.collections = {
            "users": AsyncMockCollection(),
            "settings": AsyncMockCollection(),
        }

    def __getitem__(self, name):
        return self.collections[name]


def test_mongodb_user_repository():
    async def _test():
        db = AsyncMockDatabase()
        repo = UserRepository(db)

        # Create user
        u1 = await repo.create_user(user_id=111, referrer_id=None)
        assert u1["user_id"] == 111
        assert u1["referrals_count"] == 0

        # Increment referrals
        new_count = await repo.increment_referrals(111)
        assert new_count == 1
        assert await repo.get_referrals_count(111) == 1

        # Check user exists
        assert await repo.user_exists(111) is True
        assert await repo.user_exists(999) is False

        # Create second user
        await repo.create_user(user_id=222, referrer_id=111)

        # Stats
        stats = await repo.get_stats(threshold=1)
        assert stats["total_users"] == 2
        assert stats["completed_users"] == 1
        assert stats["total_referrals"] == 1
        assert len(stats["top_referrers"]) == 1

        # All user IDs
        uids = await repo.get_all_user_ids()
        assert 111 in uids
        assert 222 in uids

    asyncio.run(_test())


def test_mongodb_settings_repository():
    async def _test():
        db = AsyncMockDatabase()
        repo = SettingsRepository(db)

        config = BotConfig(
            BOT_TOKEN="1:x",
            ADMIN_IDS="111",
            REQUIRED_REFERRALS=3,
            CLOSED_CHANNEL_LINK="https://t.me/+old_link",
            SUBSCRIPTION_CHECK_ENABLED=True,
            MANDATORY_CHANNELS='[{"name": "Initial", "url": "https://t.me/init", "id": -1001}]',
            MONGODB_URI="mongodb://localhost:27017",
        )

        settings = await repo.get_settings(config)
        assert len(settings.mandatory_channels) == 1
        assert settings.subscription_check_enabled is True

        # Toggle subscription check
        updated = await repo.toggle_subscription_check()
        assert updated.subscription_check_enabled is False

        # Add channel
        new_ch = ChannelModel(name="New Ch", url="https://t.me/new_ch", id=-1002)
        updated = await repo.add_channel(new_ch)
        assert len(updated.mandatory_channels) == 2

        # Remove channel
        updated = await repo.remove_channel(-1001)
        assert len(updated.mandatory_channels) == 1
        assert updated.mandatory_channels[0].id == -1002

        # Update closed link
        updated = await repo.update_settings({"closed_channel_link": "https://t.me/+new_link"})
        assert updated.closed_channel_link == "https://t.me/+new_link"

    asyncio.run(_test())
