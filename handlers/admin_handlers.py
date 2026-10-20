"""Admin dashboard and management handlers with strict permission checks."""

from __future__ import annotations

import logging
from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BotConfig, ChannelConfig
from database.models import ChannelModel
from database.repository import SettingsRepository, UserRepository
from handlers.middlewares import IsAdminFilter
from keyboards.admin_keyboards import (
    get_admin_channels_keyboard,
    get_admin_main_keyboard,
    get_admin_media_keyboard,
    get_admin_settings_keyboard,
    get_admin_stats_keyboard,
    get_broadcast_confirm_keyboard,
    get_cancel_keyboard,
    get_confirm_channel_delete_keyboard,
    get_promo_preview_keyboard,
)
from services.broadcast_service import BroadcastService
from services.statistics_service import StatisticsService
from services.subscription_service import SubscriptionService
from utils.telegram_helpers import safe_send

logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_threshold = State()
    waiting_for_closed_link = State()
    waiting_for_share_text = State()
    waiting_for_promo_text = State()
    waiting_for_promo_confirm = State()
    waiting_for_photo1 = State()
    waiting_for_photo2 = State()
    waiting_for_welcome_sticker = State()
    waiting_for_success_sticker = State()
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_confirm = State()


def create_admin_router(
    config: BotConfig,
    user_repo: UserRepository,
    settings_repo: SettingsRepository,
    broadcast_service: BroadcastService,
    statistics_service: Optional[StatisticsService] = None,
) -> Router:
    """Factory creating admin router protected by IsAdminFilter."""
    router = Router(name="admin_router")
    admin_filter = IsAdminFilter(config)
    router.message.filter(admin_filter)
    router.callback_query.filter(admin_filter)

    if statistics_service is None:
        statistics_service = StatisticsService(user_repo, settings_repo)

    async def get_current_settings():
        return await settings_repo.get_settings(config)

    # ---------- Main Admin Dashboard ----------
    @router.message(Command("admin", "panel"))
    async def cmd_admin_panel(message: types.Message, state: FSMContext):
        await state.clear()
        text = (
            "🛠 <b>Admin Boshqaruv Paneli</b>\n\n"
            "Quyidagi bo'limlardan birini tanlang:"
        )
        await message.answer(text, reply_markup=get_admin_main_keyboard())

    @router.callback_query(F.data == "admin_main")
    async def cb_admin_main(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        text = (
            "🛠 <b>Admin Boshqaruv Paneli</b>\n\n"
            "Quyidagi bo'limlardan birini tanlang:"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_admin_main_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_admin_main_keyboard())
        await call.answer()

    @router.callback_query(F.data == "admin_cancel_action")
    async def cb_admin_cancel(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await call.answer("Amal bekor qilindi.")
        await cb_admin_main(call, state)

    # ---------- 1. Statistics ----------
    @router.callback_query(F.data.in_(["admin_stats", "admin_stats_refresh"]))
    async def cb_admin_stats(call: types.CallbackQuery, bot: Bot):
        force_refresh = (call.data == "admin_stats_refresh")
        if force_refresh:
            await call.answer("⏳ Statistika yangilanmoqda, kuting...")
        else:
            await call.answer()

        try:
            stats = await statistics_service.get_statistics(
                bot=bot, config=config, force_refresh=force_refresh
            )
            text = StatisticsService.format_statistics_message(stats)
        except Exception as e:
            logger.error(f"Error fetching statistics: {e}", exc_info=True)
            text = f"❌ Statistikani yuklashda xatolik yuz berdi: {e}"

        kb = get_admin_stats_keyboard()
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            await call.message.answer(text, reply_markup=kb)

    # ---------- 2. Channels Management ----------
    @router.callback_query(F.data == "admin_channels")
    async def cb_admin_channels(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        text = (
            "📢 <b>Majburiy Kanallar Boshqaruvi</b>\n\n"
            f"Jami kanallar soni: <b>{len(settings.mandatory_channels)} ta</b>\n"
            "Kanallarni yoqish/o'chirish yoki yangi kanal qo'shish mumkin:"
        )
        kb = get_admin_channels_keyboard(settings.mandatory_channels, settings.subscription_check_enabled)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            await call.message.answer(text, reply_markup=kb)
        await call.answer()

    @router.callback_query(F.data == "admin_sub_toggle")
    async def cb_sub_toggle(call: types.CallbackQuery, state: FSMContext):
        settings = await settings_repo.toggle_subscription_check()
        status_str = "yoqildi" if settings.subscription_check_enabled else "o'chirildi"
        await call.answer(f"Obuna tekshirish {status_str}!")
        await cb_admin_channels(call, state)

    @router.callback_query(F.data.startswith("admin_ch_del_confirm_"))
    async def cb_ch_del_confirm(call: types.CallbackQuery, state: FSMContext):
        ch_id = int(call.data.replace("admin_ch_del_confirm_", ""))
        await settings_repo.remove_channel(ch_id)
        await call.answer("Kanal o'chirildi!", show_alert=True)
        await cb_admin_channels(call, state)

    @router.callback_query(F.data.startswith("admin_ch_del_"))
    async def cb_ch_del_prompt(call: types.CallbackQuery):
        ch_id = int(call.data.replace("admin_ch_del_", ""))
        text = f"⚠️ Haqiqatan ham ushbu kanalni (ID: <code>{ch_id}</code>) o'chirmoqchimisiz?"
        await call.message.edit_text(text, reply_markup=get_confirm_channel_delete_keyboard(ch_id))
        await call.answer()

    @router.callback_query(F.data == "admin_ch_add")
    async def cb_ch_add(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_channel)
        text = (
            "➕ <b>Yangi kanal qo'shish</b>\n\n"
            "Kanal ma'lumotlarini quyidagi formatda yuboring:\n"
            "<code>Kanal Nomi | https://t.me/kanal_linki | -1001234567890</code>\n\n"
            "<i>Masalan:</i>\n"
            "<code>Arab Tili | https://t.me/+AbCdEfGhIjK | -1001234567890</code>\n\n"
            "❗️ <i>Eslatma: A'zolikni tekshira olishi uchun bot ushbu kanalda ma'mur (admin) bo'lishi shart!</i>"
        )
        await call.message.edit_text(text, reply_markup=get_cancel_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_channel)
    async def msg_save_channel(message: types.Message, state: FSMContext, bot: Bot):
        text = (message.text or "").strip()
        parts = [p.strip() for p in text.split("|")]
        if len(parts) != 3:
            await message.answer(
                "❌ Format noto'g'ri! Iltimos, ma'lumotlarni quyidagicha yuboring:\n"
                "<code>Kanal Nomi | Havola | Kanal ID</code>",
                reply_markup=get_cancel_keyboard(),
            )
            return

        name, url, ch_id_str = parts
        if not (url.startswith("https://t.me/") or url.startswith("http://t.me/")):
            await message.answer("❌ Kanal havolasi https://t.me/... bilan boshlanishi kerak!", reply_markup=get_cancel_keyboard())
            return

        try:
            ch_id = int(ch_id_str)
        except ValueError:
            await message.answer("❌ Kanal ID si butun son bo'lishi kerak (masalan, -1001234567890)!", reply_markup=get_cancel_keyboard())
            return

        channel = ChannelModel(name=name, url=url, id=ch_id)
        await settings_repo.add_channel(channel)

        # Check bot access in channel
        is_admin_in_ch, admin_msg = await SubscriptionService.verify_channel_access(bot, ch_id)

        await state.clear()
        status_icon = "✅" if is_admin_in_ch else "⚠️"
        await message.answer(
            f"{status_icon} <b>Kanal muvaffaqiyatli saqlandi!</b>\n\n"
            f"📢 Nomi: {name}\n"
            f"🔗 Havola: {url}\n"
            f"🆔 ID: <code>{ch_id}</code>\n\n"
            f"<b>Bot huquqi holati:</b> {admin_msg}",
            reply_markup=get_admin_main_keyboard(),
        )

    # ---------- 3. Marathon Settings ----------
    @router.callback_query(F.data == "admin_settings")
    async def cb_admin_settings(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        text = (
            "⚙️ <b>Marafon Sozlamalari</b>\n\n"
            f"🎯 <b>Talab qilinadigan referallar:</b> {settings.required_referrals} ta\n"
            f"🔗 <b>Yopiq kanal havolasi:</b> {settings.closed_channel_link}\n\n"
            "O'zgartirish uchun kerakli tugmani bosing:"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_admin_settings_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_admin_settings_keyboard())
        await call.answer()

    @router.callback_query(F.data == "admin_set_threshold")
    async def cb_set_threshold(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_threshold)
        await call.message.edit_text(
            "🎯 <b>Yangi referal chegarasini kiriting (masalan, 3):</b>",
            reply_markup=get_cancel_keyboard(),
        )
        await call.answer()

    @router.message(AdminStates.waiting_for_threshold)
    async def msg_save_threshold(message: types.Message, state: FSMContext):
        val = (message.text or "").strip()
        if not val.isdigit() or int(val) < 1:
            await message.answer("❌ Iltimos, 1 yoki undan katta butun son kiriting:", reply_markup=get_cancel_keyboard())
            return

        new_thresh = int(val)
        await settings_repo.update_settings({"required_referrals": new_thresh})
        await state.clear()
        await message.answer(
            f"✅ Referal chegarasi <b>{new_thresh} ta</b> qilib o'zgartirildi!",
            reply_markup=get_admin_main_keyboard(),
        )

    @router.callback_query(F.data == "admin_set_closed_link")
    async def cb_set_closed_link(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_closed_link)
        await call.message.edit_text(
            "🔗 <b>Marafon o'tkaziladigan yopiq kanal havolasini yuboring:</b>\n"
            "<i>(Masalan: https://t.me/+AbCdEfGhIjK)</i>",
            reply_markup=get_cancel_keyboard(),
        )
        await call.answer()

    @router.message(AdminStates.waiting_for_closed_link)
    async def msg_save_closed_link(message: types.Message, state: FSMContext):
        url = (message.text or "").strip()
        if not (url.startswith("https://t.me/") or url.startswith("http://t.me/")):
            await message.answer("❌ Havola https://t.me/... bilan boshlanishi kerak!", reply_markup=get_cancel_keyboard())
            return

        await settings_repo.update_settings({"closed_channel_link": url})
        await state.clear()
        await message.answer(
            f"✅ Yopiq kanal havolasi muvaffaqiyatli saqlandi:\n{url}",
            reply_markup=get_admin_main_keyboard(),
        )

    # ---------- 4. Media and Texts ----------
    @router.callback_query(F.data == "admin_media")
    async def cb_admin_media(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        p1 = "Bor" if settings.photo_1 else "Yo'q"
        p2 = "Bor" if settings.photo_2 else "Yo'q"
        ws = "Bor" if settings.welcome_sticker else "Yo'q"
        ss = "Bor" if settings.success_sticker else "Yo'q"

        text = (
            "🖼 <b>Media va Matnlar Sozlamasi</b>\n\n"
            f"🖼 Rasm 1: <b>{p1}</b>\n"
            f"🖼 Rasm 2: <b>{p2}</b>\n"
            f"🌟 Xush kelibsiz stikeri: <b>{ws}</b>\n"
            f"🎉 G'alaba stikeri: <b>{ss}</b>\n\n"
            "Tahrirlash uchun kerakli bo'limni tanlang:"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_admin_media_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_admin_media_keyboard())
        await call.answer()

    @router.callback_query(F.data.in_(["admin_edit_promo", "admin_set_share_text"]))
    async def cb_edit_promo_text(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_promo_text)
        text = (
            "📝 <b>Asosiy xabarni tahrirlash</b>\n\n"
            "Yangi asosiy reklama posti xabarini yuboring.\n\n"
            "💡 <i>Qalin (bold), kursiv (italic), havola (link), blockquote va boshqa Telegram HTML teglari to'liq qo'llab-quvvatlanadi.</i>\n\n"
            "❗️ <b>Muhim:</b> Matnda foydalanuvchining shaxsiy taklif havolasi joylashishi uchun "
            "<code>{link}</code> tegini qoldirishni unutmang!\n\n"
            "<i>Masalan: &lt;a href=\"{link}\"&gt;Botdan ro'yxatdan o'ting va marafonga qo'shiling.&lt;/a&gt;</i>"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_cancel_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_cancel_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_promo_text)
    async def msg_receive_promo_text(message: types.Message, state: FSMContext, bot: Bot):
        text = (message.html_text or message.text or "").strip()
        if not text:
            await message.answer(
                "❌ Bo'sh bo'lmagan xabar yuboring:",
                reply_markup=get_cancel_keyboard(),
            )
            return

        if "{link}" not in text:
            await message.answer(
                "❌ Xabarda <code>{link}</code> tegi bo'lishi shart!\n\n"
                "Ushbu teg o'rniga har bir foydalanuvchining shaxsiy referal havolasi qo'yiladi. "
                "Iltimos, <code>{link}</code> tegini qoldirib qayta yuboring:",
                reply_markup=get_cancel_keyboard(),
            )
            return

        # Validate that format succeeds with sample link
        bot_info = await bot.get_me()
        bot_username = bot_info.username or "ArabiyaBoost_bot"
        sample_link = f"https://t.me/{bot_username}?start=123456789"
        try:
            preview_formatted = text.format(link=sample_link)
        except Exception as e:
            await message.answer(
                f"❌ Matn formatlashda xatolik yuz berdi: {e}. Iltimos, qayta yuboring:",
                reply_markup=get_cancel_keyboard(),
            )
            return

        await state.update_data(pending_promo_text=text)
        await state.set_state(AdminStates.waiting_for_promo_confirm)

        preview_msg = (
            "👁 <b>Yangi xabar ko'rinishi (Preview):</b>\n\n"
            f"{preview_formatted}\n\n"
            "────────────────────\n"
            "Ushbu xabarni asosiy reklama posti sifatida saqlashni tasdiqlaysizmi?"
        )
        await message.answer(preview_msg, reply_markup=get_promo_preview_keyboard())

    @router.callback_query(F.data == "admin_promo_confirm", AdminStates.waiting_for_promo_confirm)
    async def cb_promo_confirm(call: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        new_text = data.get("pending_promo_text")
        await state.clear()

        if not new_text:
            await call.answer("Xatolik: Yangi matn topilmadi.", show_alert=True)
            await cb_admin_main(call, state)
            return

        await settings_repo.update_settings({"share_text": new_text})
        success_text = (
            "✅ <b>Asosiy reklama xabari muvaffaqiyatli saqlandi!</b>\n\n"
            "Yangi xabar darhol kuchga kirdi va barcha yangi foydalanuvchilarga yuboriladi. "
            "U bot qayta ishga tushganda ham MongoDB da saqlanib qoladi."
        )
        try:
            await call.message.edit_text(success_text, reply_markup=get_admin_main_keyboard())
        except Exception:
            await call.message.answer(success_text, reply_markup=get_admin_main_keyboard())
        await call.answer("Muvaffaqiyatli saqlandi!")

    @router.callback_query(F.data.in_(["admin_set_photo1", "admin_set_photo2", "admin_set_welcome_sticker", "admin_set_success_sticker"]))
    async def cb_set_media_items(call: types.CallbackQuery, state: FSMContext):
        mapping = {
            "admin_set_photo1": (AdminStates.waiting_for_photo1, "🖼 Rasm 1 ning yangi file_id sini yuboring:"),
            "admin_set_photo2": (AdminStates.waiting_for_photo2, "🖼 Rasm 2 ning yangi file_id sini yuboring:"),
            "admin_set_welcome_sticker": (AdminStates.waiting_for_welcome_sticker, "🌟 Xush kelibsiz stikerining yangi file_id sini yuboring:"),
            "admin_set_success_sticker": (AdminStates.waiting_for_success_sticker, "🎉 G'alaba stikerining yangi file_id sini yuboring:"),
        }
        st, prompt = mapping[call.data]
        await state.set_state(st)
        await call.message.edit_text(prompt, reply_markup=get_cancel_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_photo1)
    async def msg_save_photo1(message: types.Message, state: FSMContext):
        val = (message.text or "").strip()
        if not val:
            await message.answer("❌ Bo'sh bo'lmagan file_id yuboring:", reply_markup=get_cancel_keyboard())
            return
        await settings_repo.update_settings({"photo_1": val})
        await state.clear()
        await message.answer("✅ Rasm 1 ID saqlandi!", reply_markup=get_admin_main_keyboard())

    @router.message(AdminStates.waiting_for_photo2)
    async def msg_save_photo2(message: types.Message, state: FSMContext):
        val = (message.text or "").strip()
        if not val:
            await message.answer("❌ Bo'sh bo'lmagan file_id yuboring:", reply_markup=get_cancel_keyboard())
            return
        await settings_repo.update_settings({"photo_2": val})
        await state.clear()
        await message.answer("✅ Rasm 2 ID saqlandi!", reply_markup=get_admin_main_keyboard())

    @router.message(AdminStates.waiting_for_welcome_sticker)
    async def msg_save_welcome_sticker(message: types.Message, state: FSMContext):
        val = (message.text or "").strip()
        if not val:
            await message.answer("❌ Bo'sh bo'lmagan file_id yuboring:", reply_markup=get_cancel_keyboard())
            return
        await settings_repo.update_settings({"welcome_sticker": val})
        await state.clear()
        await message.answer("✅ Xush kelibsiz stikeri saqlandi!", reply_markup=get_admin_main_keyboard())

    @router.message(AdminStates.waiting_for_success_sticker)
    async def msg_save_success_sticker(message: types.Message, state: FSMContext):
        val = (message.text or "").strip()
        if not val:
            await message.answer("❌ Bo'sh bo'lmagan file_id yuboring:", reply_markup=get_cancel_keyboard())
            return
        await settings_repo.update_settings({"success_sticker": val})
        await state.clear()
        await message.answer("✅ G'alaba stikeri saqlandi!", reply_markup=get_admin_main_keyboard())

    # ---------- 5. Broadcast (Safe Message Sending) ----------
    @router.callback_query(F.data == "admin_broadcast")
    async def cb_admin_broadcast(call: types.CallbackQuery, state: FSMContext):
        if broadcast_service.is_running:
            await call.answer("⚠️ Hozirda boshqa xabar tarqatish jarayoni ketmoqda. Iltimos, kuting.", show_alert=True)
            return

        await state.set_state(AdminStates.waiting_for_broadcast_message)
        text = (
            "✉️ <b>Barcha foydalanuvchilarga xabar tarqatish</b>\n\n"
            "Yubormoqchi bo'lgan xabaringizni yuboring (matn, rasm, video yoki istalgan post)."
        )
        try:
            await call.message.edit_text(text, reply_markup=get_cancel_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_cancel_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_broadcast_message)
    async def msg_receive_broadcast(message: types.Message, state: FSMContext):
        user_ids = await user_repo.get_all_user_ids()
        recipient_count = len(user_ids)

        if recipient_count == 0:
            await state.clear()
            await message.answer("⚠️ Botda hali hech qanday foydalanuvchi yo'q.", reply_markup=get_admin_main_keyboard())
            return

        await state.update_data(
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            recipient_count=recipient_count,
        )
        await state.set_state(AdminStates.waiting_for_broadcast_confirm)

        confirm_text = (
            "⚠️ <b>Xabar tarqatishni tasdiqlang:</b>\n\n"
            f"👥 Qabul qiluvchilar soni: <b>{recipient_count} ta foydalanuvchi</b>\n\n"
            "Haqiqatan ham ushbu xabarni barcha foydalanuvchilarga yubormoqchimisiz?"
        )
        await message.answer(confirm_text, reply_markup=get_broadcast_confirm_keyboard())

    @router.callback_query(F.data == "admin_broadcast_confirm", AdminStates.waiting_for_broadcast_confirm)
    async def cb_broadcast_confirm(call: types.CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        from_chat_id = data.get("from_chat_id")
        message_id = data.get("message_id")
        await state.clear()

        if not from_chat_id or not message_id:
            await call.answer("Xatolik: Xabar ma'lumotlari topilmadi.", show_alert=True)
            await cb_admin_main(call, state)
            return

        if broadcast_service.is_running:
            await call.answer("⚠️ Boshqa xabar tarqatish jarayoni faol!", show_alert=True)
            return

        await call.message.edit_text("⏳ <b>Xabar tarqatish boshlandi... Iltimos, yakunlanishini kuting.</b>")
        await call.answer()

        user_ids = await user_repo.get_all_user_ids()

        try:
            results = await broadcast_service.broadcast_message(
                bot=bot,
                user_ids=user_ids,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            report_text = (
                "✅ <b>Xabar tarqatish yakunlandi!</b>\n\n"
                f"👥 Jami qabul qiluvchilar: <b>{results['total']} ta</b>\n"
                f"📤 Muvaffaqiyatli yetkazildi: <b>{results['sent']} ta</b>\n"
                f"⚠️ Yetkazilmadi (bloklangan/ochirilgan): <b>{results['failed']} ta</b>"
            )
        except Exception as e:
            logger.error(f"Broadcast failed: {e}")
            report_text = f"❌ Xabar tarqatishda xatolik yuz berdi: {e}"

        await call.message.answer(report_text, reply_markup=get_admin_main_keyboard())

    # ---------- Admin File ID Helper Handlers ----------
    @router.message(F.photo)
    async def get_photo_id(m: types.Message):
        """Return Telegram file ID for photos sent by administrators."""
        await m.answer(f"<code>{m.photo[-1].file_id}</code>")

    @router.message(F.sticker)
    async def get_sticker_id(m: types.Message):
        """Return Telegram file ID for stickers sent by administrators."""
        await m.answer(f"<code>{m.sticker.file_id}</code>")

    return router
