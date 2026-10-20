"""Inline keyboards for admin dashboard and administrative workflows."""

from __future__ import annotations

from typing import Any, List
from aiogram import types
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Generate admin main dashboard keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"))
    builder.row(types.InlineKeyboardButton(text="📢 Kanallarni boshqarish", callback_data="admin_channels"))
    builder.row(types.InlineKeyboardButton(text="📝 Asosiy xabarni tahrirlash", callback_data="admin_edit_promo"))
    builder.row(types.InlineKeyboardButton(text="⚙️ Marafon sozlamalari", callback_data="admin_settings"))
    builder.row(types.InlineKeyboardButton(text="🖼 Media va Matnlar", callback_data="admin_media"))
    builder.row(types.InlineKeyboardButton(text="✉️ Xabar yuborish (Broadcast)", callback_data="admin_broadcast"))
    return builder.as_markup()


def get_admin_channels_keyboard(
    channels: List[Any], sub_enabled: bool
) -> InlineKeyboardMarkup:
    """Generate channels management keyboard with toggle and channel list."""
    builder = InlineKeyboardBuilder()

    toggle_text = "🟢 Obuna tekshirish: Yoqilgan" if sub_enabled else "🔴 Obuna tekshirish: O'chirilgan"
    builder.row(types.InlineKeyboardButton(text=toggle_text, callback_data="admin_sub_toggle"))

    for ch in channels:
        name = ch.name if hasattr(ch, "name") else ch.get("name", "Kanal")
        ch_id = ch.id if hasattr(ch, "id") else ch.get("id", 0)
        builder.row(
            types.InlineKeyboardButton(text=f"📢 {name}", url=getattr(ch, "url", ch.get("url", ""))),
            types.InlineKeyboardButton(text="❌ O'chirish", callback_data=f"admin_ch_del_{ch_id}"),
        )

    builder.row(types.InlineKeyboardButton(text="➕ Yangi kanal qo'shish", callback_data="admin_ch_add"))
    builder.row(types.InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="admin_main"))
    return builder.as_markup()


def get_confirm_channel_delete_keyboard(ch_id: int) -> InlineKeyboardMarkup:
    """Confirmation dialog before deleting a channel."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⚠️ Ha, o'chirilsin", callback_data=f"admin_ch_del_confirm_{ch_id}"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_channels"),
    )
    return builder.as_markup()


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
