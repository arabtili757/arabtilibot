"""Service for checking user subscriptions to mandatory Telegram channels."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple
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
    async def verify_channel_access(
        bot: Bot, channel_id: int
    ) -> Tuple[bool, str, Optional[str]]:
        """Verify whether the bot has administrative privileges in a channel to check members.

        Preflight check using Telegram Bot API:
        1. Call getChat to verify that the bot can access the channel.
        2. Call getChatMember with the bot's own ID to check its membership status and administrator privileges.
        3. Reject the addition if the bot is not an administrator or Telegram permissions are insufficient.
        """
        try:
            bot_info = await bot.get_me()
            bot_id = bot_info.id
        except Exception:
            bot_id = getattr(bot, "id", None)

        # 1. Verify channel accessibility via getChat
        try:
            chat = await bot.get_chat(chat_id=channel_id)
            chat_title = getattr(chat, "title", None) or str(channel_id)
        except Exception as e:
            logger.warning(f"Preflight getChat failed for channel {channel_id}: {e}")
            return (
                False,
                f"Kanalga ulanib bo'lmadi ({e}). Iltimos, kanal ID to'g'riligini va bot kanalga qo'shilganligini tekshiring.",
                None,
            )

        # 2. Verify bot administrator permissions via getChatMember
        try:
            bot_member = await bot.get_chat_member(chat_id=channel_id, user_id=bot_id)
            status = str(getattr(bot_member.status, "value", bot_member.status))
            if status in ("administrator", "creator"):
                return True, "Bot kanal ma'muri hisoblanadi va a'zolikni tekshirish ruxsatiga ega.", chat_title
            return (
                False,
                "Bot kanalda ma'mur (admin) emas! Kanalni qo'shish uchun avval botni kanalga qo'shib, unga administrator huquqini berishingiz shart.",
                chat_title,
            )
        except Exception as e:
            logger.warning(f"Preflight getChatMember failed for channel {channel_id}: {e}")
            return (
                False,
                f"Botning kanaldagi a'zolik holatini tekshirishda xatolik yuz berdi ({e}). Iltimos, bot kanalga qo'shilib admin qilinganini tekshiring.",
                chat_title,
            )
