"""Admin dashboard and management handlers with strict permission checks."""

from __future__ import annotations

import logging
from typing import Optional
from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BotConfig, ChannelConfig, DEFAULT_START_MESSAGE
from database.models import ChannelModel
from database.repository import SettingsRepository, UserRepository
from handlers.middlewares import IsAdminFilter, is_authorized_admin
from keyboards.admin_keyboards import (
    get_admin_channels_keyboard,
    get_admin_delete_picker_keyboard,
    get_admin_list_keyboard,
    get_admin_main_keyboard,
    get_admin_media_keyboard,
    get_admin_mgmt_keyboard,
    get_admin_settings_keyboard,
    get_admin_stats_keyboard,
    get_broadcast_confirm_keyboard,
    get_cancel_keyboard,
    get_cancel_to_channels_keyboard,
    get_cancel_to_mgmt_keyboard,
    get_cancel_to_start_msg_keyboard,
    get_channels_delete_picker_keyboard,
    get_channels_list_keyboard,
    get_confirm_admin_add_keyboard,
    get_confirm_admin_delete_keyboard,
    get_confirm_channel_add_keyboard,
    get_confirm_channel_delete_keyboard,
    get_confirm_start_message_keyboard,
    get_promo_preview_keyboard,
    get_start_message_keyboard,
)
from services.broadcast_service import BroadcastService
from services.statistics_service import StatisticsService
from services.subscription_service import SubscriptionService
from utils.telegram_helpers import safe_send

logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    # Channel management states
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
    waiting_for_channel_url = State()
    waiting_for_channel_confirm = State()

    # Admin management states
    waiting_for_admin_id = State()
    waiting_for_admin_confirm = State()
    waiting_for_admin_del_id = State()

    # Start message management states
    waiting_for_start_message = State()
    waiting_for_start_message_confirm = State()

    # Marathon settings states
    waiting_for_threshold = State()
    waiting_for_closed_link = State()

    # Promotional text & media states
    waiting_for_share_text = State()
    waiting_for_promo_text = State()
    waiting_for_promo_confirm = State()
    waiting_for_photo1 = State()
    waiting_for_photo2 = State()
    waiting_for_welcome_sticker = State()
    waiting_for_success_sticker = State()

    # Broadcast states
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
    admin_filter = IsAdminFilter(config, settings_repo)
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
        is_protected = config.is_protected_admin(message.from_user.id)
        role_label = "Himoyalangan Bosh Administrator 👑" if is_protected else "Administrator 👮‍♂️"
        text = (
            f"🛠 <b>Admin Boshqaruv Paneli</b>\n"
            f"👤 Sizning darajangiz: <b>{role_label}</b>\n\n"
            "Quyidagi bo'limlardan birini tanlang:"
        )
        await message.answer(text, reply_markup=get_admin_main_keyboard())

    @router.callback_query(F.data == "admin_main")
    async def cb_admin_main(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        is_protected = config.is_protected_admin(call.from_user.id)
        role_label = "Himoyalangan Bosh Administrator 👑" if is_protected else "Administrator 👮‍♂️"
        text = (
            f"🛠 <b>Admin Boshqaruv Paneli</b>\n"
            f"👤 Sizning darajangiz: <b>{role_label}</b>\n\n"
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

    # ---------- 👥 Admin Management ----------
    @router.callback_query(F.data == "admin_mgmt")
    async def cb_admin_mgmt(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        protected_count = len(config.all_protected_admin_ids)
        dynamic_count = len(settings.admin_ids)
        text = (
            "👥 <b>Adminlarni boshqarish</b>\n\n"
            f"🛡 Himoyalangan asosiy administratorlar: <b>{protected_count} ta</b>\n"
            f"👮‍♂️ Qo'shimcha administratorlar: <b>{dynamic_count} ta</b>\n\n"
            "Quyidagi amallardan birini tanlang:"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_admin_mgmt_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_admin_mgmt_keyboard())
        await call.answer()

    @router.callback_query(F.data == "admin_list")
    async def cb_admin_list(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        protected_lines = "\n".join(
            [f"• <code>{aid}</code> (Himoyalangan Asosiy Admin)" for aid in sorted(config.all_protected_admin_ids)]
        )
        if not settings.admin_ids:
            admins_lines = "<i>Hozircha qo'shimcha administratorlar mavjud emas.</i>"
        else:
            admins_lines = "\n".join([f"• <code>{aid}</code> (Qo'shimcha Administrator)" for aid in settings.admin_ids])

        text = (
            "📋 <b>Bot Administratorlari Ro'yxati</b>\n\n"
            f"🛡 <b>Himoyalangan asosiy administratorlar:</b>\n{protected_lines}\n\n"
            f"👮‍♂️ <b>Qo'shimcha administratorlar (Dinamik):</b>\n{admins_lines}"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_admin_list_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_admin_list_keyboard())
        await call.answer()

    @router.callback_query(F.data == "admin_add_prompt")
    async def cb_admin_add_prompt(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_admin_id)
        text = (
            "➕ <b>Yangi administrator qo'shish</b>\n\n"
            "Yangi adminning Telegram <b>raqamli foydalanuvchi ID</b> sini kiriting:\n"
            "<i>(Masalan: <code>123456789</code>)</i>\n\n"
            "💡 <i>Foydalanuvchi o'z ID sini @userinfobot orqali bilib olishi mumkin.</i>"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_cancel_to_mgmt_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_cancel_to_mgmt_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_admin_id)
    async def msg_receive_admin_id(message: types.Message, state: FSMContext):
        raw_id = (message.text or "").strip()
        if not raw_id.isdigit() or int(raw_id) <= 0:
            await message.answer(
                "❌ Noto'g'ri ID! Telegram ID faqat musbat butun sondan iborat bo'lishi kerak. Qayta kiriting:",
                reply_markup=get_cancel_to_mgmt_keyboard(),
            )
            return

        new_admin_id = int(raw_id)

        # Reject if already a protected administrator
        if config.is_protected_admin(new_admin_id):
            await message.answer(
                f"❌ Foydalanuvchi <code>{new_admin_id}</code> allaqachon himoyalangan administrator hisoblanadi!",
                reply_markup=get_cancel_to_mgmt_keyboard(),
            )
            return

        # Reject if already in dynamic admin list
        settings = await get_current_settings()
        if new_admin_id in settings.admin_ids:
            await message.answer(
                f"❌ Foydalanuvchi <code>{new_admin_id}</code> allaqachon administratorlar ro'yxatida mavjud!",
                reply_markup=get_cancel_to_mgmt_keyboard(),
            )
            return

        await state.update_data(pending_admin_id=new_admin_id)
        await state.set_state(AdminStates.waiting_for_admin_confirm)

        confirm_text = (
            "⚠️ <b>Administrator qo'shishni tasdiqlang:</b>\n\n"
            f"👤 Telegram ID: <code>{new_admin_id}</code>\n\n"
            "Ushbu foydalanuvchiga administrator huquqini berishni tasdiqlaysizmi?"
        )
        await message.answer(confirm_text, reply_markup=get_confirm_admin_add_keyboard())

    @router.callback_query(F.data == "admin_add_confirm", AdminStates.waiting_for_admin_confirm)
    async def cb_admin_add_confirm(call: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        new_admin_id = data.get("pending_admin_id")
        await state.clear()

        if not new_admin_id:
            await call.answer("Xatolik: Admin ID topilmadi.", show_alert=True)
            await cb_admin_mgmt(call, state)
            return

        # Save in MongoDB persistently
        await settings_repo.add_admin(new_admin_id)

        success_text = (
            f"✅ <b>Administrator muvaffaqiyatli tayinlandi!</b>\n\n"
            f"👤 Telegram ID: <code>{new_admin_id}</code>\n\n"
            "Ushbu hisobga barcha administrator imkoniyatlari berildi va bot qayta ishga tushganda ham saqlanib qoladi."
        )
        try:
            await call.message.edit_text(success_text, reply_markup=get_admin_mgmt_keyboard())
        except Exception:
            await call.message.answer(success_text, reply_markup=get_admin_mgmt_keyboard())
        await call.answer("Admin muvaffaqiyatli saqlandi!")

    @router.callback_query(F.data == "admin_del_menu")
    async def cb_admin_del_menu(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        # Ordinary removable admins: exclude protected root/env admins and caller's own ID
        removable_admins = [
            aid for aid in settings.admin_ids
            if not config.is_protected_admin(aid) and aid != call.from_user.id
        ]
        if not removable_admins:
            try:
                await call.message.edit_text(
                    "ℹ️ <b>Hozircha o'chirish uchun qo'shimcha administratorlar mavjud emas.</b>\n\n"
                    "<i>(Himoyalangan asosiy administratorlar va o'zingizning hisobingiz o'chirilmaydi).</i>",
                    reply_markup=get_cancel_to_mgmt_keyboard(),
                )
            except Exception:
                await call.message.answer(
                    "ℹ️ <b>Hozircha o'chirish uchun qo'shimcha administratorlar mavjud emas.</b>\n\n"
                    "<i>(Himoyalangan asosiy administratorlar va o'zingizning hisobingiz o'chirilmaydi).</i>",
                    reply_markup=get_cancel_to_mgmt_keyboard(),
                )
            await call.answer()
            return

        text = "➖ <b>Olib tashlamoqchi bo'lgan administratorni tanlang:</b>"
        kb = get_admin_delete_picker_keyboard(removable_admins)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            await call.message.answer(text, reply_markup=kb)
        await call.answer()

    @router.callback_query(F.data == "admin_del_by_input")
    async def cb_admin_del_by_input(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_admin_del_id)
        text = (
            "⌨️ <b>Administratorni ID orqali olib tashlash</b>\n\n"
            "Olib tashlamoqchi bo'lgan administratorning Telegram ID sini yuboring:"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_cancel_to_mgmt_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_cancel_to_mgmt_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_admin_del_id)
    async def msg_receive_admin_del_id(message: types.Message, state: FSMContext):
        raw_id = (message.text or "").strip()
        if not raw_id.isdigit() or int(raw_id) <= 0:
            await message.answer("❌ Iltimos, to'g'ri musbat son kiriting:", reply_markup=get_cancel_to_mgmt_keyboard())
            return

        target_id = int(raw_id)
        if target_id == message.from_user.id:
            await message.answer(
                "❌ Siz o'z administratorlik huquqingizni o'chira olmaysiz!",
                reply_markup=get_cancel_to_mgmt_keyboard(),
            )
            return

        if config.is_protected_admin(target_id):
            await message.answer(
                "❌ Himoyalangan asosiy administratorlarni o'chirib yoki tushirib bo'lmaydi!",
                reply_markup=get_cancel_to_mgmt_keyboard(),
            )
            return

        settings = await get_current_settings()
        if target_id not in settings.admin_ids:
            await message.answer(
                f"❌ Foydalanuvchi <code>{target_id}</code> administratorlar ro'yxatida topilmadi!",
                reply_markup=get_cancel_to_mgmt_keyboard(),
            )
            return

        confirm_text = (
            "⚠️ <b>Administratorni olib tashlashni tasdiqlang:</b>\n\n"
            f"👤 Telegram ID: <code>{target_id}</code>\n\n"
            "Haqiqatan ham ushbu foydalanuvchidan administratorlik huquqini olib tashlamoqchimisiz?"
        )
        await message.answer(confirm_text, reply_markup=get_confirm_admin_delete_keyboard(target_id))

    @router.callback_query(F.data.startswith("admin_del_prompt_"))
    async def cb_admin_del_prompt(call: types.CallbackQuery):
        target_id = int(call.data.replace("admin_del_prompt_", ""))
        if config.is_protected_admin(target_id):
            await call.answer("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)
            return
        if target_id == call.from_user.id:
            await call.answer("❌ O'zingizni o'chira olmaysiz!", show_alert=True)
            return

        text = (
            "⚠️ <b>Administratorni olib tashlashni tasdiqlang:</b>\n\n"
            f"👤 Telegram ID: <code>{target_id}</code>\n\n"
            "Haqiqatan ham ushbu foydalanuvchidan administratorlik huquqini olib tashlamoqchimisiz?"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_confirm_admin_delete_keyboard(target_id))
        except Exception:
            await call.message.answer(text, reply_markup=get_confirm_admin_delete_keyboard(target_id))
        await call.answer()

    @router.callback_query(F.data.startswith("admin_del_confirm_"))
    async def cb_admin_del_confirm(call: types.CallbackQuery, state: FSMContext):
        target_id = int(call.data.replace("admin_del_confirm_", ""))
        if config.is_protected_admin(target_id):
            await call.answer("Himoyalangan administratorlarni o'chirib bo'lmaydi!", show_alert=True)
            return
        if target_id == call.from_user.id:
            await call.answer("❌ O'zingizni o'chira olmaysiz!", show_alert=True)
            return

        try:
            await settings_repo.remove_admin(target_id, config=config)
            await call.answer("Administrator muvaffaqiyatli olib tashlandi!", show_alert=True)
        except ValueError as e:
            await call.answer(f"Xatolik: {e}", show_alert=True)
        await cb_admin_mgmt(call, state)


    # ---------- 💬 Start Message Management ----------
    @router.callback_query(F.data == "admin_start_msg")
    async def cb_admin_start_message(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        current_msg = settings.start_message or DEFAULT_START_MESSAGE
        text = (
            "💬 <b>/start Xabari Boshqaruvi</b>\n\n"
            "<b>Hozirgi /start xabari:</b>\n"
            f"<blockquote>{current_msg}</blockquote>\n\n"
            "<i>Ushbu xabar foydalanuvchilar botga /start yuborganda ko'rsatiladi. "
            "Uni o'zgartirishingiz yoki istalgan payt standart holatiga qaytarishingiz mumkin.</i>"
        )
        kb = get_start_message_keyboard()
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            await call.message.answer(text, reply_markup=kb)
        await call.answer()

    @router.callback_query(F.data == "admin_start_msg_edit")
    async def cb_admin_start_message_edit(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_start_message)
        text = (
            "✏️ <b>Yangi /start xabarini tahrirlash</b>\n\n"
            "Foydalanuvchilar /start yuborganda ko'rsatiladigan yangi xabarni yuboring.\n\n"
            "💡 <i>HTML teglari to'liq qo'llab-quvvatlanadi (&lt;b&gt;, &lt;i&gt;, &lt;blockquote&gt;, &lt;a href=\"...\"&gt; va h.k.).</i>"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_cancel_to_start_msg_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_cancel_to_start_msg_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_start_message)
    async def msg_receive_start_message(message: types.Message, state: FSMContext):
        text = (message.html_text or message.text or "").strip()
        if not text:
            await message.answer(
                "❌ Bo'sh bo'lmagan xabar yuboring:",
                reply_markup=get_cancel_to_start_msg_keyboard(),
            )
            return

        await state.update_data(pending_start_message=text)
        await state.set_state(AdminStates.waiting_for_start_message_confirm)

        preview_text = (
            "👁 <b>Yangi /start xabari ko'rinishi (Preview):</b>\n\n"
            f"{text}\n\n"
            "────────────────────\n"
            "Ushbu xabarni yangi /start xabari sifatida saqlashni tasdiqlaysizmi?"
        )
        await message.answer(preview_text, reply_markup=get_confirm_start_message_keyboard())

    @router.callback_query(F.data == "admin_start_msg_confirm", AdminStates.waiting_for_start_message_confirm)
    async def cb_start_message_confirm(call: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        new_text = data.get("pending_start_message")
        await state.clear()

        if not new_text:
            await call.answer("Xatolik: Yangi xabar topilmadi.", show_alert=True)
            await cb_admin_start_message(call, state)
            return

        await settings_repo.update_start_message(new_text)
        success_text = (
            "✅ <b>Yangi /start xabari muvaffaqiyatli saqlandi!</b>\n\n"
            "Ushbu xabar zudlik bilan kuchga kirdi va bot qayta ishga tushganda ham MongoDB da saqlanib qoladi."
        )
        try:
            await call.message.edit_text(success_text, reply_markup=get_start_message_keyboard())
        except Exception:
            await call.message.answer(success_text, reply_markup=get_start_message_keyboard())
        await call.answer("Muvaffaqiyatli saqlandi!")

    @router.callback_query(F.data == "admin_start_msg_reset")
    async def cb_start_message_reset(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await settings_repo.reset_start_message()
        await call.answer("Standart /start xabari tiklandi!", show_alert=True)
        await cb_admin_start_message(call, state)


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

    # ---------- 2. Dynamic Mandatory Channels Management ----------
    @router.callback_query(F.data == "admin_channels")
    async def cb_admin_channels(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        status_text = "🟢 Yoqilgan" if settings.subscription_check_enabled else "🔴 O'chirilgan"
        text = (
            "📢 <b>Majburiy kanallar boshqaruvi</b>\n\n"
            f"Jami kanallar soni: <b>{len(settings.mandatory_channels)} ta</b>\n"
            f"Obunani tekshirish holati: <b>{status_text}</b>\n\n"
            "Quyidagi amallardan birini tanlang:"
        )
        kb = get_admin_channels_keyboard(settings.subscription_check_enabled, len(settings.mandatory_channels))
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            await call.message.answer(text, reply_markup=kb)
        await call.answer()

    @router.callback_query(F.data == "admin_ch_list")
    async def cb_ch_list(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        if not settings.mandatory_channels:
            text = (
                "📋 <b>Majburiy kanallar ro'yxati</b>\n\n"
                "<i>Hozircha hech qanday kanal sozlanmagan.</i>\n\n"
                "Yangi kanal qo'shish uchun pastdagi tugmani bosing."
            )
        else:
            lines = []
            for i, ch in enumerate(settings.mandatory_channels, 1):
                lines.append(
                    f"{i}. <b>{ch.name}</b>\n"
                    f"   🆔 ID: <code>{ch.id}</code>\n"
                    f"   🔗 <a href=\"{ch.url}\">{ch.url}</a>"
                )
            text = (
                "📋 <b>Majburiy kanallar ro'yxati:</b>\n\n"
                + "\n\n".join(lines)
            )

        kb = get_channels_list_keyboard(settings.mandatory_channels)
        try:
            await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            await call.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        await call.answer()

    @router.callback_query(F.data == "admin_sub_toggle")
    async def cb_sub_toggle(call: types.CallbackQuery, state: FSMContext):
        settings = await settings_repo.toggle_subscription_check()
        status_str = "yoqildi" if settings.subscription_check_enabled else "o'chirildi"
        await call.answer(f"Obuna tekshirish {status_str}!")
        await cb_admin_channels(call, state)

    @router.callback_query(F.data == "admin_ch_del_menu")
    async def cb_ch_del_menu(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        settings = await get_current_settings()
        if not settings.mandatory_channels:
            try:
                await call.message.edit_text(
                    "ℹ️ <b>Hozircha o'chirish uchun kanallar mavjud emas.</b>",
                    reply_markup=get_cancel_to_channels_keyboard(),
                )
            except Exception:
                await call.message.answer(
                    "ℹ️ <b>Hozircha o'chirish uchun kanallar mavjud emas.</b>",
                    reply_markup=get_cancel_to_channels_keyboard(),
                )
            await call.answer()
            return

        text = "➖ <b>O'chirmoqchi bo'lgan kanalni tanlang:</b>"
        kb = get_channels_delete_picker_keyboard(settings.mandatory_channels)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            await call.message.answer(text, reply_markup=kb)
        await call.answer()

    @router.callback_query(F.data.startswith("admin_ch_del_prompt_"))
    async def cb_ch_del_prompt(call: types.CallbackQuery):
        ch_id = int(call.data.replace("admin_ch_del_prompt_", ""))
        settings = await get_current_settings()
        ch = next((c for c in settings.mandatory_channels if c.id == ch_id), None)
        ch_name = ch.name if ch else "Kanal"
        text = (
            "⚠️ <b>Kanalni o'chirishni tasdiqlang:</b>\n\n"
            f"📢 Nomi: <b>{ch_name}</b>\n"
            f"🆔 ID: <code>{ch_id}</code>\n\n"
            "Haqiqatan ham ushbu kanalni majburiy kanallar ro'yxatidan o'chirmoqchimisiz?\n\n"
            "<i>(Bu faqat botning obuna talablaridan olib tashlaydi, Telegramdagi kanal o'chirilmaydi)</i>"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_confirm_channel_delete_keyboard(ch_id))
        except Exception:
            await call.message.answer(text, reply_markup=get_confirm_channel_delete_keyboard(ch_id))
        await call.answer()

    @router.callback_query(F.data.startswith("admin_ch_del_confirm_"))
    async def cb_ch_del_confirm(call: types.CallbackQuery, state: FSMContext):
        ch_id = int(call.data.replace("admin_ch_del_confirm_", ""))
        await settings_repo.remove_channel(ch_id)
        await call.answer("Kanal majburiy a'zolikdan muvaffaqiyatli olib tashlandi!", show_alert=True)
        await cb_admin_channels(call, state)

    @router.callback_query(F.data == "admin_ch_add")
    async def cb_ch_add(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_channel_id)
        text = (
            "➕ <b>Kanal qo'shish — 1/3-qadam</b>\n\n"
            "Kanalning <b>Telegram ID</b> sini yuboring:\n"
            "<i>(Masalan: <code>-1001234567890</code>)</i>\n\n"
            "💡 <i>Yoki barcha ma'lumotlarni bir xabarda quyidagicha yuborishingiz mumkin:</i>\n"
            "<code>-1001234567890 | Kanal Nomi | https://t.me/kanal_linki</code>\n\n"
            "❗️ <b>Majburiy shart:</b> Bot avval ushbu kanalga qo'shilgan va <b>administrator</b> qilingan bo'lishi shart!"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_cancel_to_channels_keyboard())
        except Exception:
            await call.message.answer(text, reply_markup=get_cancel_to_channels_keyboard())
        await call.answer()

    @router.message(AdminStates.waiting_for_channel_id)
    async def msg_receive_channel_id(message: types.Message, state: FSMContext, bot: Bot):
        text_content = (message.text or "").strip()
        parts = [p.strip() for p in text_content.split("|")]

        settings = await get_current_settings()
        existing_ids = {c.id for c in settings.mandatory_channels}

        # Case 1: Pipe-delimited single message
        if len(parts) == 3:
            raw_id, name, url = parts
            try:
                ch_id = int(raw_id)
            except ValueError:
                await message.answer("❌ Kanal ID si butun son bo'lishi kerak!", reply_markup=get_cancel_to_channels_keyboard())
                return

            if not (url.startswith("https://t.me/") or url.startswith("http://t.me/")):
                await message.answer("❌ Kanal havolasi https://t.me/... bilan boshlanishi kerak!", reply_markup=get_cancel_to_channels_keyboard())
                return

            if ch_id in existing_ids:
                await message.answer(f"❌ <code>{ch_id}</code> ID ga ega kanal allaqachon mavjud!", reply_markup=get_cancel_to_channels_keyboard())
                return

            # Preflight check using Telegram Bot API
            is_valid, msg, chat_title = await SubscriptionService.verify_channel_access(bot, ch_id)
            if not is_valid:
                await message.answer(
                    f"❌ <b>Bot kanal ma'muri emas yoki kanalga ulanib bo'lmadi!</b>\n\n"
                    f"{msg}\n\n"
                    f"Iltimos, avval botni kanalga admin qilib, so'ng qayta urinib ko'ring.",
                    reply_markup=get_cancel_to_channels_keyboard(),
                )
                return

            await state.update_data(pending_channel={"id": ch_id, "name": name, "url": url})
            await state.set_state(AdminStates.waiting_for_channel_confirm)

            confirm_text = (
                "📋 <b>Kanal ma'lumotlarini tasdiqlang:</b>\n\n"
                f"📢 Nomi: <b>{name}</b>\n"
                f"🆔 ID: <code>{ch_id}</code>\n"
                f"🔗 Havola: {url}\n\n"
                f"✅ <b>Bot adminligi muvaffaqiyatli tekshirildi!</b>\n\n"
                "Ushbu kanalni majburiy kanallar ro'yxatiga qo'shishni tasdiqlaysizmi?"
            )
            await message.answer(confirm_text, reply_markup=get_confirm_channel_add_keyboard())
            return

        # Case 2: Just the channel ID
        try:
            ch_id = int(text_content)
        except ValueError:
            await message.answer(
                "❌ Noto'g'ri format! Kanal ID sini butun son ko'rinishida yuboring (masalan: <code>-1001234567890</code>):",
                reply_markup=get_cancel_to_channels_keyboard(),
            )
            return

        if ch_id in existing_ids:
            await message.answer(
                f"❌ <code>{ch_id}</code> ID ga ega kanal allaqachon majburiy kanallar ro'yxatida mavjud!",
                reply_markup=get_cancel_to_channels_keyboard(),
            )
            return

        # Preflight check using Telegram Bot API
        is_valid, msg, chat_title = await SubscriptionService.verify_channel_access(bot, ch_id)
        if not is_valid:
            await message.answer(
                f"❌ <b>Bot administrator huquqiga ega emas yoki kanalga ulanib bo'lmadi!</b>\n\n"
                f"{msg}\n\n"
                f"Iltimos, avval botni kanalga qo'shib, unga <b>administrator</b> huquqini bering, so'ngra kanal ID sini qayta yuboring:",
                reply_markup=get_cancel_to_channels_keyboard(),
            )
            return

        await state.update_data(temp_ch_id=ch_id, temp_ch_title=chat_title)
        await state.set_state(AdminStates.waiting_for_channel_name)

        suggested_name = f"\n<i>(Kanal asl nomi: {chat_title})</i>" if chat_title else ""
        step2_text = (
            f"✅ <b>Bot adminligi muvaffaqiyatli tasdiqlandi!</b>\n\n"
            f"➕ <b>Kanal qo'shish — 2/3-qadam</b>\n\n"
            f"Kanalning <b>ko'rinadigan nomini</b> kiriting:{suggested_name}"
        )
        await message.answer(step2_text, reply_markup=get_cancel_to_channels_keyboard())

    @router.message(AdminStates.waiting_for_channel_name)
    async def msg_receive_channel_name(message: types.Message, state: FSMContext):
        name = (message.text or "").strip()
        if not name:
            await message.answer("❌ Kanal nomini kiriting:", reply_markup=get_cancel_to_channels_keyboard())
            return

        await state.update_data(temp_ch_name=name)
        await state.set_state(AdminStates.waiting_for_channel_url)

        step3_text = (
            "➕ <b>Kanal qo'shish — 3/3-qadam</b>\n\n"
            "Kanalning <b>Telegram havolasini</b> yuboring:\n"
            "<i>(Masalan: <code>https://t.me/arobic_world</code> yoki <code>https://t.me/+AbCdEfGhIjK</code>)</i>"
        )
        await message.answer(step3_text, reply_markup=get_cancel_to_channels_keyboard())

    @router.message(AdminStates.waiting_for_channel_url)
    async def msg_receive_channel_url(message: types.Message, state: FSMContext):
        url = (message.text or "").strip()
        if not (url.startswith("https://t.me/") or url.startswith("http://t.me/")):
            await message.answer(
                "❌ Havola https://t.me/... bilan boshlanishi kerak! Qayta kiriting:",
                reply_markup=get_cancel_to_channels_keyboard(),
            )
            return

        data = await state.get_data()
        ch_id = data.get("temp_ch_id")
        ch_name = data.get("temp_ch_name")

        await state.update_data(pending_channel={"id": ch_id, "name": ch_name, "url": url})
        await state.set_state(AdminStates.waiting_for_channel_confirm)

        confirm_text = (
            "📋 <b>Kanal ma'lumotlarini tasdiqlang:</b>\n\n"
            f"📢 Nomi: <b>{ch_name}</b>\n"
            f"🆔 ID: <code>{ch_id}</code>\n"
            f"🔗 Havola: {url}\n\n"
            f"✅ <b>Bot adminligi muvaffaqiyatli tekshirildi!</b>\n\n"
            "Ushbu kanalni majburiy kanallar ro'yxatiga qo'shishni tasdiqlaysizmi?"
        )
        await message.answer(confirm_text, reply_markup=get_confirm_channel_add_keyboard())

    @router.callback_query(F.data == "admin_ch_add_confirm", AdminStates.waiting_for_channel_confirm)
    async def cb_ch_add_confirm(call: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        pending = data.get("pending_channel")
        await state.clear()

        if not pending:
            await call.answer("Xatolik: Kanal ma'lumotlari topilmadi.", show_alert=True)
            await cb_admin_channels(call, state)
            return

        channel = ChannelModel(**pending)
        await settings_repo.add_channel(channel)

        success_text = (
            "✅ <b>Kanal muvaffaqiyatli saqlandi!</b>\n\n"
            f"📢 Nomi: <b>{channel.name}</b>\n"
            f"🆔 ID: <code>{channel.id}</code>\n"
            f"🔗 Havola: {channel.url}\n\n"
            "Ushbu kanal darhol barcha obuna tekshiruvlarida ishtirok etadi."
        )
        try:
            await call.message.edit_text(success_text, reply_markup=get_admin_channels_keyboard(True))
        except Exception:
            await call.message.answer(success_text, reply_markup=get_admin_channels_keyboard(True))
        await call.answer("Kanal muvaffaqiyatli qo'shildi!")

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
