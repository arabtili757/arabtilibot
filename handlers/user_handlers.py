"""User handlers with automatic subscription verification and personalized sharing."""

from __future__ import annotations

import logging
from typing import Optional
from aiogram import Bot, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InputMediaPhoto

from config import BotConfig, DEFAULT_START_MESSAGE
from database.models import BotSettingsDocument
from database.repository import SettingsRepository, UserRepository
from keyboards.user_keyboards import build_share_url, get_share_keyboard, get_sub_keyboard
from services.referral_service import ReferralService
from services.subscription_service import SubscriptionService
from utils.telegram_helpers import NO_PREVIEW, safe_send, safe_send_media_group, safe_sticker

logger = logging.getLogger(__name__)


def create_user_router(
    config: BotConfig,
    user_repo: UserRepository,
    settings_repo: SettingsRepository,
) -> Router:
    """Factory creating user router with automatic verification and sharing flows."""
    router = Router(name="user_router")
    referral_service = ReferralService(user_repo)

    async def get_current_settings() -> BotSettingsDocument:
        return await settings_repo.get_settings(config)

    @router.message(CommandStart())
    async def command_start_handler(
        message: types.Message, command: CommandObject, bot: Bot
    ):
        user_id = message.from_user.id
        ref_id = command.args
        settings = await get_current_settings()

        # 1. Save user and referral parameter as a pending registration in MongoDB
        # Preserves user's original referral parameter throughout the process
        await referral_service.save_pending_registration(user_id=user_id, ref_arg=ref_id)

        # 2. Check if user is ALREADY subscribed to all required channels
        is_sub = await SubscriptionService.is_subscribed(
            bot=bot,
            user_id=user_id,
            channels=settings.mandatory_channels,
            check_enabled=settings.subscription_check_enabled,
        )

        if not is_sub:
            # User has not yet joined all mandatory channels; send channel links without manual confirmation button
            await safe_sticker(bot, user_id, settings.welcome_sticker)
            text = settings.start_message or DEFAULT_START_MESSAGE
            await message.answer(
                text,
                reply_markup=get_sub_keyboard(settings.mandatory_channels),
            )
            return

        # If already subscribed to every required channel, complete immediately
        await complete_registration_and_respond(user_id=user_id, bot=bot, settings=settings)

    @router.chat_member()
    async def chat_member_updated_handler(event: types.ChatMemberUpdated, bot: Bot):
        """Telegram chat_member update handler for automatic subscription verification."""
        chat_id = event.chat.id
        settings = await get_current_settings()

        # Only process updates from mandatory channels
        mandatory_ids = {ch.id for ch in settings.mandatory_channels}
        if chat_id not in mandatory_ids:
            return

        if event.new_chat_member.user.is_bot:
            return

        user_id = event.new_chat_member.user.id

        # When a user joins or leaves a mandatory channel, automatically check membership in ALL required channels
        is_sub = await SubscriptionService.is_subscribed(
            bot=bot,
            user_id=user_id,
            channels=settings.mandatory_channels,
            check_enabled=settings.subscription_check_enabled,
        )

        await user_repo.update_subscription_status(user_id, is_sub)

        # As soon as the user is subscribed to every required channel, complete registration
        if is_sub:
            user = await user_repo.get_user(user_id)
            if user and user.get("status") == "pending":
                await complete_registration_and_respond(user_id=user_id, bot=bot, settings=settings)

    @router.callback_query(F.data.startswith("checksub_"))
    async def fallback_check_sub_handler(call: types.CallbackQuery, bot: Bot):
        """Fallback callback handler for legacy confirmation buttons from prior versions."""
        user_id = call.from_user.id
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

        await complete_registration_and_respond(user_id=user_id, bot=bot, settings=settings)

    async def complete_registration_and_respond(
        user_id: int, bot: Bot, settings: BotSettingsDocument
    ):
        """Complete registration atomically and deliver welcome, stats, promotional album, and share button."""
        result = await referral_service.complete_registration(
            user_id=user_id,
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

        # Build personalized referral and share links
        bot_info = await bot.get_me()
        bot_username = bot_info.username or "ArabiyaBoost_bot"
        my_link, share_url = build_share_url(bot_username, user_id)
        share_kb = get_share_keyboard(share_url)

        if result.is_completed:
            await safe_send(
                bot,
                user_id,
                f"✅ <b>Siz kerakli miqdordagi do'stlaringizni taklif qilgansiz!</b>\n\n"
                f"<blockquote>Marafonga kirish uchun ssilka: {settings.closed_channel_link}</blockquote>\n"
                f"📊 Jami takliflaringiz: <b>{result.user_referrals_count} ta.</b>",
                reply_markup=share_kb,
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

        # Format promotional post text
        try:
            post_text = settings.share_text.format(link=my_link)
        except Exception:
            post_text = f"{settings.share_text}\n\n{my_link}"

        delivered_media = False
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
                    delivered_media = True
            except Exception as e:
                logger.warning(f"Media group failed for {user_id}: {e}")

        if delivered_media:
            # Telegram does not support attaching inline keyboards directly to media groups;
            # send short follow-up message containing the inline sharing button directly below it
            await safe_send(
                bot,
                user_id,
                "👇 <b>Do'stlaringizga ulashish uchun quyidagi tugmani bosing:</b>",
                reply_markup=share_kb,
            )
        else:
            # Fallback text message with share button attached directly
            await safe_send(
                bot,
                user_id,
                post_text,
                reply_markup=share_kb,
                link_preview_options=NO_PREVIEW,
            )

    @router.message(Command("admin", "panel"))
    async def cmd_unauthorized_admin(message: types.Message):
        """Notification for unauthorized users attempting to access /admin."""
        await message.answer(
            f"❌ <b>Ruxsat etilmadi.</b>\n\n"
            f"Sizda ushbu botning administratorlik huquqi mavjud emas.\n"
            f"🆔 Sizning Telegram ID: <code>{message.from_user.id}</code>"
        )

    return router

