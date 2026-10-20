"""Service for calculating and caching accurate bot statistics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import zoneinfo
from aiogram import Bot

from config import BotConfig
from database.repository import SettingsRepository, UserRepository

logger = logging.getLogger(__name__)

TASHKENT_TZ = zoneinfo.ZoneInfo("Asia/Tashkent")


def get_tashkent_bounds() -> tuple[datetime, datetime, datetime]:
    """Calculate Tashkent local now, start of today in UTC, and start of 7d ago in UTC."""
    now_tashkent = datetime.now(TASHKENT_TZ)
    start_today_tashkent = now_tashkent.replace(hour=0, minute=0, second=0, microsecond=0)
    start_today_utc = start_today_tashkent.astimezone(timezone.utc)
    start_7d_utc = (start_today_tashkent - timedelta(days=6)).astimezone(timezone.utc)
    return now_tashkent, start_today_utc, start_7d_utc


class StatisticsService:
    """Calculates comprehensive statistics based on MongoDB and Telegram channel membership."""

    def __init__(
        self,
        user_repo: UserRepository,
        settings_repo: SettingsRepository,
        cache_ttl_seconds: int = 300,  # 5 minutes
    ) -> None:
        self.user_repo = user_repo
        self.settings_repo = settings_repo
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def get_statistics(
        self,
        bot: Bot,
        config: BotConfig,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Fetch complete statistics with caching and rate-limited Telegram audit."""
        async with self._lock:
            now_utc = datetime.now(timezone.utc)
            if (
                not force_refresh
                and self._cache is not None
                and self._cache_time is not None
                and (now_utc - self._cache_time).total_seconds() < self.cache_ttl_seconds
            ):
                return self._cache

            now_tashkent, start_today_utc, start_7d_utc = get_tashkent_bounds()
            settings = await self.settings_repo.get_settings(config)

            # 1. MongoDB user and referral stats
            db_stats = await self.user_repo.get_detailed_user_stats(
                start_today_utc=start_today_utc,
                start_7d_utc=start_7d_utc,
                threshold=settings.required_referrals,
            )

            # 2. Channel membership audit for completed users
            completed_user_ids = await self.user_repo.get_all_completed_user_ids()
            channel_stats: List[Dict[str, Any]] = []
            eligible_users_count = 0
            pending_or_unsub_count = db_stats["pending_users"]
            total_unverifiable_users = 0

            if not settings.subscription_check_enabled:
                # If subscription checking is disabled, all completed users are eligible
                eligible_users_count = db_stats["total_registered"]
                for ch in settings.mandatory_channels:
                    channel_stats.append({
                        "name": ch.name,
                        "id": ch.id,
                        "subscribed": db_stats["total_registered"],
                        "not_subscribed": 0,
                        "unverifiable": 0,
                        "bot_is_admin": True,
                        "admin_warning": None,
                    })
            elif not settings.mandatory_channels:
                eligible_users_count = db_stats["total_registered"]
            else:
                # Check bot rights in each channel first
                channel_bot_rights: Dict[int, bool] = {}
                channel_warnings: Dict[int, Optional[str]] = {}

                for ch in settings.mandatory_channels:
                    try:
                        bot_member = await bot.get_chat_member(chat_id=ch.id, user_id=bot.id)
                        status = str(getattr(bot_member.status, "value", bot_member.status))
                        if status in ("administrator", "creator"):
                            channel_bot_rights[ch.id] = True
                            channel_warnings[ch.id] = None
                        else:
                            channel_bot_rights[ch.id] = False
                            channel_warnings[ch.id] = "Bot kanalda admin emas! A'zolikni tekshirib bo'lmaydi."
                    except Exception as e:
                        channel_bot_rights[ch.id] = False
                        channel_warnings[ch.id] = f"Kanalga ulanish xatosi: {e}"

                # Audit each user's membership across channels
                user_sub_map: Dict[int, set[int]] = {uid: set() for uid in completed_user_ids}
                user_unverifiable_map: Dict[int, bool] = {uid: False for uid in completed_user_ids}

                ch_sub_counts: Dict[int, int] = {ch.id: 0 for ch in settings.mandatory_channels}
                ch_unsub_counts: Dict[int, int] = {ch.id: 0 for ch in settings.mandatory_channels}
                ch_unverifiable_counts: Dict[int, int] = {ch.id: 0 for ch in settings.mandatory_channels}

                for ch in settings.mandatory_channels:
                    ch_id = ch.id
                    if not channel_bot_rights.get(ch_id, False):
                        # Bot has no access to this channel; all users are unverifiable for this channel
                        ch_unverifiable_counts[ch_id] = len(completed_user_ids)
                        for uid in completed_user_ids:
                            user_unverifiable_map[uid] = True
                        continue

                    # Rate-limited query for completed users
                    for uid in completed_user_ids:
                        try:
                            member = await bot.get_chat_member(chat_id=ch_id, user_id=uid)
                            status = str(getattr(member.status, "value", member.status))
                            if status in ("member", "administrator", "creator"):
                                ch_sub_counts[ch_id] += 1
                                user_sub_map[uid].add(ch_id)
                            elif status in ("left", "kicked") or (status == "restricted" and not getattr(member, "is_member", True)):
                                ch_unsub_counts[ch_id] += 1
                            else:
                                ch_sub_counts[ch_id] += 1
                                user_sub_map[uid].add(ch_id)
                        except Exception as ex:
                            logger.debug(f"Audit get_chat_member error for {uid} in {ch_id}: {ex}")
                            ch_unverifiable_counts[ch_id] += 1
                            user_unverifiable_map[uid] = True

                        await asyncio.sleep(0.01)

                total_mandatory = len(settings.mandatory_channels)
                for uid in completed_user_ids:
                    if len(user_sub_map[uid]) == total_mandatory:
                        eligible_users_count += 1
                    else:
                        if not user_unverifiable_map[uid]:
                            pending_or_unsub_count += 1
                        else:
                            total_unverifiable_users += 1

                for ch in settings.mandatory_channels:
                    channel_stats.append({
                        "name": ch.name,
                        "id": ch.id,
                        "subscribed": ch_sub_counts[ch.id],
                        "not_subscribed": ch_unsub_counts[ch.id],
                        "unverifiable": ch_unverifiable_counts[ch.id],
                        "bot_is_admin": channel_bot_rights.get(ch.id, False),
                        "admin_warning": channel_warnings.get(ch.id),
                    })

            # Format top referrers
            bot_info = await bot.get_me()
            bot_username = bot_info.username or "ArabiyaBoost_bot"

            top_referrers_formatted = []
            for item in db_stats["top_referrers"]:
                uid = item["user_id"]
                count = item["count"]
                link = f"https://t.me/{bot_username}?start={uid}"
                top_referrers_formatted.append({
                    "user_id": uid,
                    "count": count,
                    "link": link,
                })

            stats_result = {
                # A. User Statistics
                "total_users": db_stats["total_users"],
                "total_registered": db_stats["total_registered"],
                "registered_today": db_stats["registered_today"],
                "registered_7d": db_stats["registered_7d"],
                "legacy_no_timestamp": db_stats["legacy_no_timestamp"],
                "total_referred": db_stats["total_referred"],
                "eligible_users_count": eligible_users_count,
                "pending_users_count": pending_or_unsub_count,
                "total_unverifiable_users": total_unverifiable_users,
                # B. Channel Statistics
                "channel_stats": channel_stats,
                "subscription_check_enabled": settings.subscription_check_enabled,
                # C. Referral Statistics
                "total_unique_referrals": db_stats["total_referred"],
                "completed_referred_count": db_stats["total_referred"],
                "top_referrers": top_referrers_formatted,
                # Metadata
                "updated_at_tashkent": now_tashkent.strftime("%Y-%m-%d %H:%M:%S"),
            }

            self._cache = stats_result
            self._cache_time = now_utc
            return stats_result

    @staticmethod
    def format_statistics_message(stats: Dict[str, Any]) -> str:
        """Format statistics data into clean, readable Telegram HTML."""
        lines = [
            "📊 <b>BOT STATISTIKASI</b>",
            f"<i>🕒 Yangilangan vaqt: {stats['updated_at_tashkent']} (Toshkent vaqti)</i>",
            "",
            "👤 <b>A. Foydalanuvchilar statistikasi:</b>",
            f"• Jami ro'yxatdan o'tganlar: <b>{stats['total_registered']} ta</b>",
            f"• Bugun ro'yxatdan o'tganlar: <b>{stats['registered_today']} ta</b>",
            f"• Oxirgi 7 kunda ro'yxatdan o'tganlar: <b>{stats['registered_7d']} ta</b>",
            f"• Referal havola orqali kelganlar: <b>{stats['total_referred']} ta</b>",
            f"• Marafonda ishtirok etish huquqiga ega (barcha kanallarga a'zo): <b>{stats['eligible_users_count']} ta</b>",
            f"• Majburiy obunani to'liq bajarmaganlar / kutilmoqda: <b>{stats['pending_users_count']} ta</b>",
        ]

        if stats.get("legacy_no_timestamp", 0) > 0:
            lines.append(f"• <i>(Sanasiz eski foydalanuvchilar: {stats['legacy_no_timestamp']} ta)</i>")

        if stats.get("total_unverifiable_users", 0) > 0:
            lines.append(f"• ⚠️ A'zoligi tekshirib bo'lmagan foydalanuvchilar: <b>{stats['total_unverifiable_users']} ta</b>")

        lines.append("")
        lines.append("📢 <b>B. Majburiy kanallar statistikasi:</b>")

        if not stats.get("channel_stats"):
            lines.append("<i>Hozircha majburiy kanallar sozlanmagan.</i>")
        else:
            for ch in stats["channel_stats"]:
                admin_icon = "🟢" if ch.get("bot_is_admin", True) else "🔴"
                lines.append(f"{admin_icon} <b>{ch['name']}</b> (<code>{ch['id']}</code>):")
                lines.append(f"   ✅ A'zo: <b>{ch['subscribed']} ta</b>")
                lines.append(f"   ❌ A'zo emas: <b>{ch['not_subscribed']} ta</b>")
                if ch.get("unverifiable", 0) > 0:
                    lines.append(f"   ⚠️ Tekshirib bo'lmadi: <b>{ch['unverifiable']} ta</b>")
                if ch.get("admin_warning"):
                    lines.append(f"   ❗️ <i>{ch['admin_warning']}</i>")

        lines.append("")
        lines.append("🔗 <b>C. Referal statistikasi:</b>")
        lines.append(f"• Jami muvaffaqiyatli, noyob referallar: <b>{stats['total_unique_referrals']} ta</b>")
        lines.append(f"• Obunani to'liq bajargan referallar: <b>{stats['completed_referred_count']} ta</b>")
        lines.append("")
        lines.append("🏆 <b>Eng faol taklif qiluvchilar (Top):</b>")

        if not stats.get("top_referrers"):
            lines.append("<i>Hozircha muvaffaqiyatli referallar mavjud emas.</i>")
        else:
            for idx, item in enumerate(stats["top_referrers"], start=1):
                lines.append(
                    f"{idx}. ID: <code>{item['user_id']}</code> — <b>{item['count']} ta</b>\n"
                    f"   🔗 <code>{item['link']}</code>"
                )

        return "\n".join(lines)
