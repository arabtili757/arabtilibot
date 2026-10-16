"""Service for checking user subscriptions to mandatory Telegram channels."""

from __future__ import annotations

import logging
from typing import Any, List, Tuple
from aiogram import Bot

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Handles verification of user membership in required channels."""

    @staticmethod
    async def is_subscribed(
        bot: Bot,
        user_id: int,
        channels: List[Any],
        check_enabled: bool = True,
    ) -> bool:
        """Check whether the user is subscribed to all configured channels.

        If subscription checking is disabled, returns True immediately.
        """
        if not check_enabled or not channels:
            return True

        for ch in channels:
            ch_id = ch.id if hasattr(ch, "id") else ch.get("id")
            try:
                member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
                status = str(getattr(member.status, "value", member.status))
                if status in ("left", "kicked"):
                    return False
                if status == "restricted" and not getattr(member, "is_member", True):
                    return False
            except Exception as e:
                logger.error(
                    f"Subscription check failed for channel {ch_id} and user {user_id}: {e}"
                )
                return False

        return True

    @staticmethod
    async def verify_channel_access(bot: Bot, channel_id: int) -> Tuple[bool, str]:
        """Verify whether the bot has administrative privileges in a channel to check members."""
        try:
            bot_member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)
            status = str(getattr(bot_member.status, "value", bot_member.status))
            if status in ("administrator", "creator"):
                return True, "Bot kanal ma'muri hisoblanadi."
            return (
                False,
                "Bot kanalda ma'mur (admin) emas. A'zolikni tekshirish uchun botga admin huquqi berilishi shart.",
            )
        except Exception as e:
            return (
                False,
                f"Kanalga ulanishda xatolik yuz berdi: {e}. Bot kanalga qo'shilganligini tekshiring.",
            )
