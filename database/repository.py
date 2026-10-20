"""Repository pattern for MongoDB user and settings management."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import pymongo
from motor.motor_asyncio import AsyncIOMotorDatabase

from config import (
    BotConfig,
    DEFAULT_MANDATORY_CHANNELS,
    DEFAULT_START_MESSAGE,
    PROTECTED_ADMIN_IDS,
)
from database.models import BotSettingsDocument, ChannelModel, UserDocument, utc_now

logger = logging.getLogger(__name__)


class UserRepository:
    """Handles persistence and queries for Telegram bot users."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.db = db
        self.collection = db["users"]

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve user by Telegram user_id."""
        return await self.collection.find_one({"user_id": user_id})

    async def user_exists(self, user_id: int) -> bool:
        """Check if user exists in the database."""
        doc = await self.collection.find_one({"user_id": user_id}, {"_id": 1})
        return doc is not None

    async def save_pending_user(
        self, user_id: int, pending_referrer_id: Optional[int] = None
    ) -> tuple[bool, Dict[str, Any]]:
        """Save a pending user registration if not already present.

        Returns (is_new, user_dict). Preserves existing records and referral links.
        """
        existing = await self.get_user(user_id)
        if existing:
            return False, existing

        now = utc_now()
        doc = {
            "user_id": user_id,
            "referrer_id": None,
            "pending_referrer_id": pending_referrer_id,
            "referrals_count": 0,
            "status": "pending",
            "registered_at": None,
            "created_at": now,
            "updated_at": now,
        }
        await self.collection.update_one(
            {"user_id": user_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        user = await self.get_user(user_id)
        return True, user or doc

    async def complete_user_registration(
        self, user_id: int, referrer_id: Optional[int] = None
    ) -> tuple[bool, Dict[str, Any]]:
        """Atomically transition user from pending to completed.

        Returns (just_completed, user_dict).
        If user was already completed, returns (False, user_dict).
        """
        now = utc_now()
        set_fields: Dict[str, Any] = {
            "status": "completed",
            "registered_at": now,
            "updated_at": now,
        }
        if referrer_id is not None:
            set_fields["referrer_id"] = referrer_id

        # Atomic transition where status == 'pending'
        result = await self.collection.find_one_and_update(
            {"user_id": user_id, "status": "pending"},
            {
                "$set": set_fields,
                "$unset": {"pending_referrer_id": ""},
            },
            return_document=pymongo.ReturnDocument.AFTER,
        )
        if result:
            return True, result

        # User was already completed or not in pending state
        user = await self.get_user(user_id)
        return False, user or {}

    async def update_subscription_status(
        self, user_id: int, is_subscribed: bool
    ) -> None:
        """Update cached channel subscription status for a user."""
        await self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "is_currently_subscribed": is_subscribed,
                    "updated_at": utc_now(),
                }
            },
        )

    async def create_user(
        self, user_id: int, referrer_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Safely create a new completed user. Idempotent if user already exists."""
        now = utc_now()
        await self.collection.update_one(
            {"user_id": user_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "referrer_id": referrer_id,
                    "referrals_count": 0,
                    "status": "completed",
                    "registered_at": now,
                    "created_at": now,
                },
                "$set": {
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        user = await self.get_user(user_id)
        return user or {}

    async def increment_referrals(self, referrer_id: int) -> int:
        """Increment the referrals count for a given referrer. Returns updated count."""
        now = utc_now()
        result = await self.collection.find_one_and_update(
            {"user_id": referrer_id},
            {
                "$inc": {"referrals_count": 1},
                "$set": {"updated_at": now},
            },
            return_document=pymongo.ReturnDocument.AFTER,
        )
        if result and "referrals_count" in result:
            return int(result["referrals_count"])
        return 0

    async def get_referrals_count(self, user_id: int) -> int:
        """Get current referral count for a user."""
        doc = await self.collection.find_one(
            {"user_id": user_id}, {"referrals_count": 1}
        )
        if doc and "referrals_count" in doc:
            return int(doc["referrals_count"])
        return 0

    async def get_detailed_user_stats(
        self, start_today_utc: Any, start_7d_utc: Any, threshold: int = 3
    ) -> Dict[str, Any]:
        """Calculate detailed user and referral statistics from MongoDB."""
        total_registered = await self.collection.count_documents(
            {"status": {"$ne": "pending"}}
        )
        pending_users = await self.collection.count_documents(
            {"status": "pending"}
        )
        total_users = total_registered + pending_users

        registered_today = await self.collection.count_documents({
            "status": {"$ne": "pending"},
            "registered_at": {"$gte": start_today_utc},
        })
        registered_7d = await self.collection.count_documents({
            "status": {"$ne": "pending"},
            "registered_at": {"$gte": start_7d_utc},
        })
        legacy_no_timestamp = await self.collection.count_documents({
            "status": {"$ne": "pending"},
            "$or": [
                {"registered_at": None},
                {"registered_at": {"$exists": False}},
            ],
        })
        total_referred = await self.collection.count_documents({
            "status": {"$ne": "pending"},
            "referrer_id": {"$ne": None},
        })

        # Top referrers with real user_id and count
        top_cursor = (
            self.collection.find(
                {"status": {"$ne": "pending"}, "referrals_count": {"$gt": 0}},
                {"user_id": 1, "referrals_count": 1},
            )
            .sort("referrals_count", pymongo.DESCENDING)
            .limit(10)
        )
        top_referrers = []
        async for item in top_cursor:
            top_referrers.append({
                "user_id": item["user_id"],
                "count": item.get("referrals_count", 0),
            })

        completed_eligible_count = await self.collection.count_documents({
            "status": {"$ne": "pending"},
            "referrals_count": {"$gte": threshold},
        })

        return {
            "total_users": total_users,
            "total_registered": total_registered,
            "pending_users": pending_users,
            "registered_today": registered_today,
            "registered_7d": registered_7d,
            "legacy_no_timestamp": legacy_no_timestamp,
            "total_referred": total_referred,
            "top_referrers": top_referrers,
            "completed_eligible_count": completed_eligible_count,
        }

    async def get_stats(self, threshold: int = 3) -> Dict[str, Any]:
        """Legacy aggregate statistics for backward compatibility."""
        total_users = await self.collection.count_documents({})
        completed_users = await self.collection.count_documents(
            {"referrals_count": {"$gte": threshold}}
        )
        pending_users = max(0, total_users - completed_users)

        pipeline = [
            {"$group": {"_id": None, "total": {"$sum": "$referrals_count"}}}
        ]
        agg_res = await self.collection.aggregate(pipeline).to_list(length=1)
        total_referrals = agg_res[0]["total"] if agg_res else 0

        top_cursor = (
            self.collection.find(
                {"referrals_count": {"$gt": 0}},
                {"user_id": 1, "referrals_count": 1},
            )
            .sort("referrals_count", pymongo.DESCENDING)
            .limit(5)
        )
        top_referrers = []
        async for item in top_cursor:
            uid_str = str(item["user_id"])
            masked_id = (
                f"{uid_str[:3]}***{uid_str[-3:]}"
                if len(uid_str) >= 6
                else f"***{uid_str[-2:]}"
            )
            top_referrers.append(
                {"masked_id": masked_id, "count": item.get("referrals_count", 0)}
            )

        return {
            "total_users": total_users,
            "completed_users": completed_users,
            "pending_users": pending_users,
            "total_referrals": total_referrals,
            "top_referrers": top_referrers,
        }

    async def get_all_completed_user_ids(self) -> List[int]:
        """Fetch all registered (completed) user IDs for auditing."""
        cursor = self.collection.find({"status": {"$ne": "pending"}}, {"user_id": 1})
        user_ids: List[int] = []
        async for doc in cursor:
            if "user_id" in doc:
                user_ids.append(doc["user_id"])
        return user_ids

    async def get_all_user_ids(self) -> List[int]:
        """Fetch all user IDs for message broadcasting."""
        cursor = self.collection.find({}, {"user_id": 1})
        user_ids: List[int] = []
        async for doc in cursor:
            if "user_id" in doc:
                user_ids.append(doc["user_id"])
        return user_ids


class SettingsRepository:
    """Handles dynamic runtime settings stored in MongoDB."""

    SETTINGS_KEY = "app_settings"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.db = db
        self.collection = db["settings"]

    async def get_settings(self, fallback: BotConfig) -> BotSettingsDocument:
        """Retrieve runtime settings or initialize them with fallback defaults."""
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        if doc:
            updates: Dict[str, Any] = {}
            if "channels_initialized" not in doc:
                updates["channels_initialized"] = True
            if "admins_initialized" not in doc:
                updates["admins_initialized"] = True
                if "admin_ids" not in doc:
                    updates["admin_ids"] = list(fallback.admin_ids)
            if updates:
                updates["updated_at"] = utc_now()
                await self.collection.update_one(
                    {"key": self.SETTINGS_KEY},
                    {"$set": updates},
                )
                doc.update(updates)
            return BotSettingsDocument.model_validate(doc)

        # Initialize with fallback config for the very first time
        channels_source = (
            fallback.mandatory_channels
            if fallback.mandatory_channels
            else DEFAULT_MANDATORY_CHANNELS
        )
        initial_channels = [
            ChannelModel(name=ch.name, url=ch.url, id=ch.id)
            for ch in channels_source
        ]

        initial = BotSettingsDocument(
            key=self.SETTINGS_KEY,
            required_referrals=fallback.required_referrals,
            closed_channel_link=fallback.closed_channel_link,
            subscription_check_enabled=fallback.subscription_check_enabled,
            mandatory_channels=initial_channels,
            channels_initialized=True,
            admin_ids=list(fallback.admin_ids),
            admins_initialized=True,
            share_text=fallback.share_text,
            start_message=DEFAULT_START_MESSAGE,
            promo_images=[],
            welcome_sticker=fallback.welcome_sticker,
            success_sticker=fallback.success_sticker,
            updated_at=utc_now(),
        )
        await self.collection.update_one(
            {"key": self.SETTINGS_KEY},
            {"$set": initial.model_dump()},
            upsert=True,
        )
        return initial

    async def update_settings(self, updates: Dict[str, Any]) -> BotSettingsDocument:
        """Update runtime settings fields."""
        updates["updated_at"] = utc_now()
        await self.collection.update_one(
            {"key": self.SETTINGS_KEY},
            {"$set": updates},
            upsert=True,
        )
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        return BotSettingsDocument.model_validate(doc)

    async def update_start_message(self, message_text: str) -> BotSettingsDocument:
        """Update the /start welcome message persistently."""
        return await self.update_settings({"start_message": message_text.strip()})

    async def reset_start_message(self) -> BotSettingsDocument:
        """Reset the /start welcome message to default."""
        return await self.update_settings({"start_message": DEFAULT_START_MESSAGE})

    async def add_channel(self, channel: ChannelModel) -> BotSettingsDocument:
        """Add a mandatory channel if not already present."""
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_channels = doc.get("mandatory_channels", []) if doc else []

        # Check by id
        filtered = [ch for ch in current_channels if ch.get("id") != channel.id]
        filtered.append(channel.model_dump())

        return await self.update_settings({
            "mandatory_channels": filtered,
            "channels_initialized": True,
        })

    async def remove_channel(self, channel_id: int) -> BotSettingsDocument:
        """Remove a mandatory channel by ID."""
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_channels = doc.get("mandatory_channels", []) if doc else []
        filtered = [ch for ch in current_channels if ch.get("id") != channel_id]
        return await self.update_settings({
            "mandatory_channels": filtered,
            "channels_initialized": True,
        })

    async def toggle_subscription_check(
        self, enabled: Optional[bool] = None
    ) -> BotSettingsDocument:
        """Toggle or set subscription check status."""
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_status = doc.get("subscription_check_enabled", True) if doc else True
        new_status = not current_status if enabled is None else enabled
        return await self.update_settings({"subscription_check_enabled": new_status})

    async def get_admins(self, fallback: BotConfig) -> List[int]:
        """Get the active list of database-managed admin IDs."""
        settings = await self.get_settings(fallback)
        return settings.admin_ids

    async def get_dynamic_admin_ids(self, fallback: Optional[BotConfig] = None) -> List[int]:
        """Retrieve dynamic administrator IDs from database."""
        doc = await self.collection.find_one(
            {"key": self.SETTINGS_KEY},
            {"admin_ids": 1},
        )
        if doc and "admin_ids" in doc:
            return list(doc.get("admin_ids", []))
        if fallback:
            return list(fallback.admin_ids)
        return []

    async def add_admin(self, admin_id: int) -> BotSettingsDocument:
        """Add an administrator to MongoDB."""
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_admins = doc.get("admin_ids", []) if doc else []
        if admin_id not in current_admins:
            current_admins = list(current_admins) + [admin_id]
        return await self.update_settings({
            "admin_ids": current_admins,
            "admins_initialized": True,
        })

    async def remove_admin(self, admin_id: int, config: Optional[BotConfig] = None) -> BotSettingsDocument:
        """Remove an administrator from MongoDB, strictly protecting root/env administrators."""
        if admin_id in PROTECTED_ADMIN_IDS:
            raise ValueError(f"ID {admin_id} is a protected root administrator and cannot be removed!")
        if config and config.is_protected_admin(admin_id):
            raise ValueError(f"ID {admin_id} is a protected administrator and cannot be removed!")

        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_admins = doc.get("admin_ids", []) if doc else []
        filtered = [aid for aid in current_admins if aid != admin_id]
        return await self.update_settings({
            "admin_ids": filtered,
            "admins_initialized": True,
        })

    async def is_admin(self, user_id: int, config: BotConfig) -> bool:
        """Centralized check whether a user ID is an authorized administrator."""
        # 1. Protected root and owner administrators ALWAYS have permanent access
        if config.is_protected_admin(user_id):
            return True
        # 2. Dynamic administrators stored in MongoDB
        doc = await self.collection.find_one(
            {"key": self.SETTINGS_KEY},
            {"admin_ids": 1, "admins_initialized": 1},
        )
        if doc and doc.get("admins_initialized"):
            return user_id in doc.get("admin_ids", [])
        # Fallback if DB is not yet initialized
        return user_id in config.admin_ids

    # ==========================================================================
    # Promotional Images Management
    # ==========================================================================

    async def get_promo_images(self) -> List[str]:
        """Retrieve list of promotional image Telegram file IDs."""
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        if doc and "promo_images" in doc:
            return list(doc.get("promo_images", []))
        return []

    async def add_promo_image(self, file_id: str) -> BotSettingsDocument:
        """Add a promotional image Telegram file ID if not already present."""
        clean_id = file_id.strip()
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_images = list(doc.get("promo_images", [])) if doc else []
        if clean_id not in current_images:
            current_images.append(clean_id)
        return await self.update_settings({"promo_images": current_images})

    async def remove_promo_image(self, file_id: str) -> BotSettingsDocument:
        """Remove a promotional image by its file ID."""
        clean_id = file_id.strip()
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_images = list(doc.get("promo_images", [])) if doc else []
        filtered = [fid for fid in current_images if fid != clean_id]
        return await self.update_settings({"promo_images": filtered})

    async def remove_promo_image_by_index(self, index: int) -> BotSettingsDocument:
        """Remove a promotional image by its 0-based index."""
        doc = await self.collection.find_one({"key": self.SETTINGS_KEY})
        current_images = list(doc.get("promo_images", [])) if doc else []
        if 0 <= index < len(current_images):
            current_images.pop(index)
            return await self.update_settings({"promo_images": current_images})
        return BotSettingsDocument.model_validate(doc) if doc else BotSettingsDocument(
            closed_channel_link="https://t.me/+example", share_text=""
        )

    async def clear_promo_images(self) -> BotSettingsDocument:
        """Clear all promotional images."""
        return await self.update_settings({"promo_images": []})

