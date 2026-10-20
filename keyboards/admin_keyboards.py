"""Inline keyboards for admin dashboard and administrative workflows."""

from __future__ import annotations

from typing import Any, List
from aiogram import types
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_admin_main_keyboard(is_owner: bool = True) -> InlineKeyboardMarkup:
    """Generate admin main dashboard keyboard with all functional controls."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"))
    builder.row(types.InlineKeyboardButton(text="📢 Majburiy kanallar", callback_data="admin_channels"))
    builder.row(types.InlineKeyboardButton(text="💬 /start xabarini boshqarish", callback_data="admin_start_msg"))
    builder.row(types.InlineKeyboardButton(text="👥 Adminlarni boshqarish", callback_data="admin_mgmt"))
    builder.row(types.InlineKeyboardButton(text="📝 Asosiy xabarni tahrirlash", callback_data="admin_edit_promo"))
    builder.row(types.InlineKeyboardButton(text="⚙️ Marafon sozlamalari", callback_data="admin_settings"))
    builder.row(types.InlineKeyboardButton(text="🖼 Media va Matnlar", callback_data="admin_media"))
    builder.row(types.InlineKeyboardButton(text="✉️ Xabar yuborish (Broadcast)", callback_data="admin_broadcast"))
    return builder.as_markup()


# ==============================================================================
# Start Message Management Keyboards
# ==============================================================================

def get_start_message_keyboard() -> InlineKeyboardMarkup:
    """Generate keyboard for start message management."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="✏️ Xabarni tahrirlash", callback_data="admin_start_msg_edit"))
    builder.row(types.InlineKeyboardButton(text="🔄 Standart xabarga qaytarish", callback_data="admin_start_msg_reset"))
    builder.row(types.InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="admin_main"))
    return builder.as_markup()


def get_confirm_start_message_keyboard() -> InlineKeyboardMarkup:
    """Confirmation keyboard for saving edited start message."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Ha, saqlansin", callback_data="admin_start_msg_confirm"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_start_msg"),
    )
    return builder.as_markup()


def get_cancel_to_start_msg_keyboard() -> InlineKeyboardMarkup:
    """Cancel button returning to start message menu."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_start_msg"))
    return builder.as_markup()



# ==============================================================================
# Admin Management Keyboards (Owner Only)
# ==============================================================================

def get_admin_mgmt_keyboard() -> InlineKeyboardMarkup:
    """Generate admin management keyboard with four core options."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add_prompt"))
    builder.row(types.InlineKeyboardButton(text="📋 Adminlar ro'yxati", callback_data="admin_list"))
    builder.row(types.InlineKeyboardButton(text="➖ Adminni olib tashlash", callback_data="admin_del_menu"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_main"))
    return builder.as_markup()


def get_admin_list_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for admin list view."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add_prompt"),
        types.InlineKeyboardButton(text="➖ Adminni olib tashlash", callback_data="admin_del_menu"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_mgmt"))
    return builder.as_markup()


def get_admin_delete_picker_keyboard(admin_ids: List[int]) -> InlineKeyboardMarkup:
    """Keyboard listing removable administrators."""
    builder = InlineKeyboardBuilder()
    for aid in admin_ids:
        builder.row(types.InlineKeyboardButton(text=f"❌ {aid} ni olib tashlash", callback_data=f"admin_del_prompt_{aid}"))
    builder.row(types.InlineKeyboardButton(text="⌨️ ID kiritish orqali", callback_data="admin_del_by_input"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_mgmt"))
    return builder.as_markup()


def get_confirm_admin_delete_keyboard(admin_id: int) -> InlineKeyboardMarkup:
    """Confirmation dialog before removing an administrator."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⚠️ Ha, olib tashlansin", callback_data=f"admin_del_confirm_{admin_id}"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_mgmt"),
    )
    return builder.as_markup()


def get_confirm_admin_add_keyboard() -> InlineKeyboardMarkup:
    """Confirmation dialog before adding an administrator."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Ha, tayinlansin", callback_data="admin_add_confirm"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_mgmt"),
    )
    return builder.as_markup()


def get_cancel_to_mgmt_keyboard() -> InlineKeyboardMarkup:
    """Cancel button returning to admin management menu."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_mgmt"))
    return builder.as_markup()


# ==============================================================================
# Mandatory Channels Management Keyboards
# ==============================================================================

def get_admin_channels_keyboard(
    sub_enabled: bool, channels_count: int = 0
) -> InlineKeyboardMarkup:
    """Generate main section menu for mandatory channels management."""
    builder = InlineKeyboardBuilder()
    toggle_icon = "🟢 Yoqilgan" if sub_enabled else "🔴 O'chirilgan"
    builder.row(types.InlineKeyboardButton(text="📋 Kanallar ro'yxati", callback_data="admin_ch_list"))
    builder.row(types.InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="admin_ch_add"))
    builder.row(types.InlineKeyboardButton(text="➖ Kanalni o'chirish", callback_data="admin_ch_del_menu"))
    builder.row(types.InlineKeyboardButton(text=f"🔄 Obunani tekshirish: {toggle_icon}", callback_data="admin_sub_toggle"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_main"))
    return builder.as_markup()


def get_channels_list_keyboard(channels: List[Any]) -> InlineKeyboardMarkup:
    """Display channels with direct links and management buttons."""
    builder = InlineKeyboardBuilder()
    for ch in channels:
        name = ch.name if hasattr(ch, "name") else ch.get("name", "Kanal")
        url = getattr(ch, "url", ch.get("url", ""))
        builder.row(types.InlineKeyboardButton(text=f"📢 {name}", url=url))

    builder.row(
        types.InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="admin_ch_add"),
        types.InlineKeyboardButton(text="➖ Kanalni o'chirish", callback_data="admin_ch_del_menu"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
    return builder.as_markup()


def get_channels_delete_picker_keyboard(channels: List[Any]) -> InlineKeyboardMarkup:
    """Display channel removal picker."""
    builder = InlineKeyboardBuilder()
    for ch in channels:
        name = ch.name if hasattr(ch, "name") else ch.get("name", "Kanal")
        ch_id = ch.id if hasattr(ch, "id") else ch.get("id", 0)
        builder.row(types.InlineKeyboardButton(text=f"❌ {name} ({ch_id})", callback_data=f"admin_ch_del_prompt_{ch_id}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_channels"))
    return builder.as_markup()


def get_confirm_channel_delete_keyboard(ch_id: int) -> InlineKeyboardMarkup:
    """Confirmation dialog before deleting a mandatory channel."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⚠️ Ha, o'chirilsin", callback_data=f"admin_ch_del_confirm_{ch_id}"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_channels"),
    )
    return builder.as_markup()


def get_confirm_channel_add_keyboard() -> InlineKeyboardMarkup:
    """Confirmation dialog before saving a new mandatory channel."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Ha, saqlansin", callback_data="admin_ch_add_confirm"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_channels"),
    )
    return builder.as_markup()


def get_cancel_to_channels_keyboard() -> InlineKeyboardMarkup:
    """Cancel button returning to channels menu."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_channels"))
    return builder.as_markup()


# ==============================================================================
# General Admin Keyboards
# ==============================================================================

def get_admin_settings_keyboard() -> InlineKeyboardMarkup:
    """Generate keyboard for changing referral threshold and closed channel link."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎯 Referal chegarasini o'zgartirish", callback_data="admin_set_threshold"))
    builder.row(types.InlineKeyboardButton(text="🔗 Yopiq kanal havolasini o'zgartirish", callback_data="admin_set_closed_link"))
    builder.row(types.InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="admin_main"))
    return builder.as_markup()


def get_admin_media_keyboard() -> InlineKeyboardMarkup:
    """Generate keyboard for editing share text, photos, and stickers."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📝 Asosiy xabarni tahrirlash", callback_data="admin_edit_promo"))
    builder.row(
        types.InlineKeyboardButton(text="🖼 Rasm 1 ID", callback_data="admin_set_photo1"),
        types.InlineKeyboardButton(text="🖼 Rasm 2 ID", callback_data="admin_set_photo2"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🌟 Xush kelibsiz stikeri", callback_data="admin_set_welcome_sticker"),
        types.InlineKeyboardButton(text="🎉 G'alaba stikeri", callback_data="admin_set_success_sticker"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="admin_main"))
    return builder.as_markup()


def get_promo_preview_keyboard() -> InlineKeyboardMarkup:
    """Confirmation keyboard for saving edited promotional message."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="admin_promo_confirm"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_cancel_action"),
    )
    return builder.as_markup()


def get_admin_stats_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for admin statistics with refresh option."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_stats_refresh"))
    builder.row(types.InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="admin_main"))
    return builder.as_markup()


def get_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirmation keyboard for broadcasting messages."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Ha, xabarni yuborish", callback_data="admin_broadcast_confirm"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_cancel_action"),
    )
    return builder.as_markup()


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel button returning to admin main menu."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_cancel_action"))
    return builder.as_markup()
