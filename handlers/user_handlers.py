"""User handlers preserving existing bot behaviors and flows."""

from __future__ import annotations

import logging
from typing import Optional
from aiogram import Bot, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import InputMediaPhoto

from config import BotConfig
from database.repository import SettingsRepository, UserRepository
from keyboards.user_keyboards import get_sub_keyboard
from services.referral_service import ReferralService
from services.subscription_service import SubscriptionService
from utils.telegram_helpers import NO_PREVIEW, safe_send, safe_send_media_group, safe_sticker

logger = logging.getLogger(__name__)


def create_user_router(
    config: BotConfig,
    user_repo: UserRepository,
    settings_repo: SettingsRepository,
) -> Router:
    """Factory creating user router with injected dependencies."""
    router = Router(name="user_router")
    referral_service = ReferralService(user_repo)

    async def get_current_settings():
        return await settings_repo.get_settings(config)

    @router.message(CommandStart())
    async def command_start_handler(
        message: types.Message, command: CommandObject, bot: Bot
    ):
        user_id = message.from_user.id
        ref_id = command.args
        settings = await get_current_settings()

        # Check subscription
        is_sub = await SubscriptionService.is_subscribed(
            bot=bot,
            user_id=user_id,
            channels=settings.mandatory_channels,
            check_enabled=settings.subscription_check_enabled,
        )

        if not is_sub:
            await safe_sticker(bot, user_id, settings.welcome_sticker)
            text = (
                "🚀 <b>Marafonda ishtirok etish uchun quyidagi kanallarga a'zo bo'ling.</b>\n\n"
                '<i>Keyin pastdagi "✅ A\'zo bo\'ldim" tugmasini bosing.</i>'
            )
            await message.answer(
                text,
                reply_markup=get_sub_keyboard(settings.mandatory_channels, ref_id),
            )
            return

        await handle_registration_and_response(user_id, ref_id, bot, settings)

    @router.callback_query(F.data.startswith("checksub_"))
    async def check_sub_handler(call: types.CallbackQuery, bot: Bot):
        user_id = call.from_user.id
        parts = call.data.split("_", 1)
        ref_id = parts[1] if len(parts) > 1 else None
        if ref_id in ("none", "", None):
            ref_id = None

        settings = await get_current_settings()

        is_sub = await SubscriptionService.is_subscribed(
            bot=bot,
            user_id=user_id,
            channels=settings.mandatory_channels,
            check_enabled=settings.subscription_check_enabled,
        )

        if not is_sub:
            await call.answer(
                "Siz hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True
            )
            return

        await call.answer()
        try:
            await call.message.delete()
        except Exception:
            pass

        await handle_registration_and_response(user_id, ref_id, bot, settings)

    async def handle_registration_and_response(
        user_id: int, ref_id: Optional[str | int], bot: Bot, settings
    ):
        result = await referral_service.process_registration(
            user_id=user_id,
            ref_arg=ref_id,
            required_referrals=settings.required_referrals,
        )

        # Notify referrer if applicable
        notif = result.referrer_notification
        if notif:
            rid = notif.referrer_id
            count = notif.current_count
            req = notif.required_count

            if notif.kind == "success":
                await safe_sticker(bot, rid, settings.success_sticker)
                await safe_send(
                    bot,
                    rid,
                    f"🎉 <b>Tabriklaymiz!</b>\n"
                    f"<blockquote>Siz {req} ta do'stingizni taklif qildingiz va shartni bajardingiz.</blockquote>\n"
                    f"👇 <b>Marafon bo'ladigan yopiq kanalga kirish uchun havola:</b>\n{settings.closed_channel_link}",
                    link_preview_options=NO_PREVIEW,
                )
            elif notif.kind == "progress":
                await safe_send(
                    bot,
                    rid,
                    f"👤 <b>Yangi do'stingiz</b> sizning havolangiz orqali botga kirdi!\n\n"
                    f"📈 Hozirgi takliflaringiz soni: <b>{count}/{req}</b> ta.",
                )
            elif notif.kind == "extra_progress":
                await safe_send(
                    bot,
                    rid,
                    f"👤 <b>Yangi do'stingiz</b> sizning havolangiz orqali botga kirdi!\n\n"
                    f"📈 Hozirgi takliflaringiz soni: <b>{count}</b> ta.",
                )

        # Respond to the user
        bot_info = await bot.get_me()
        my_link = f"https://t.me/{bot_info.username}?start={user_id}"

        if result.is_completed:
            await safe_send(
                bot,
                user_id,
                f"✅ <b>Siz kerakli miqdordagi do'stlaringizni taklif qilgansiz!</b>\n\n"
                f"<blockquote>Marafonga kirish uchun ssilka: {settings.closed_channel_link}</blockquote>\n"
                f"📊 Jami takliflaringiz: <b>{result.user_referrals_count} ta.</b>",
                link_preview_options=NO_PREVIEW,
            )
            return

        await safe_send(
            bot,
            user_id,
            f"🌟 <b>Arab tili marafoniga xush kelibsiz!</b>\n\n"
            f"<blockquote>Marafonga qo'shilish uchun <b>{settings.required_referrals} ta do'stingizni</b> taklif qiling.</blockquote>\n"
            f"👇 <i>Do'stlaringizni taklif qilish uchun pastdagi tayyor postni ularga forward qiling (uzating):</i>\n\n"
            f"📊 <b>Taklif qilgan do'stlaringiz:</b> {result.user_referrals_count}/{settings.required_referrals}",
        )

        # Send media group or fallback
        try:
            post_text = settings.share_text.format(link=my_link)
        except Exception:
            post_text = f"{settings.share_text}\n\n{my_link}"

        delivered = False
        if settings.photo_1 and settings.photo_2:
            try:
                media_group = [
                    InputMediaPhoto(
                        media=settings.photo_1,
                        caption=post_text,
                        parse_mode=ParseMode.HTML,
                    ),
                    InputMediaPhoto(media=settings.photo_2),
                ]
                res = await safe_send_media_group(bot, user_id, media_group)
                if res:
                    delivered = True
            except Exception as e:
                logger.warning(f"Media group failed for {user_id}: {e}")

        if not delivered:
            await safe_send(bot, user_id, post_text, link_preview_options=NO_PREVIEW)

    return router
