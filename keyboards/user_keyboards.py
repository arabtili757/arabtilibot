"""Inline keyboards for user interactions and subscription flows."""

from __future__ import annotations

from typing import Any, List, Optional
from aiogram import types
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_sub_keyboard(
    channels: List[Any], ref_id: Optional[Any] = None
) -> InlineKeyboardMarkup:
    """Generate inline keyboard with channel links and subscription check button.

    Preserves referral ID in callback data so it survives the subscription flow.
    """
    builder = InlineKeyboardBuilder()

    for ch in channels:
        name = ch.name if hasattr(ch, "name") else ch.get("name", "Kanal")
        url = ch.url if hasattr(ch, "url") else ch.get("url", "")
        builder.row(types.InlineKeyboardButton(text=name, url=url))

    cb_data = (
        f"checksub_{ref_id}"
        if ref_id not in (None, "", "none")
        else "checksub_none"
    )
    builder.row(
        types.InlineKeyboardButton(text="✅ A'zo bo'ldim", callback_data=cb_data)
    )

    return builder.as_markup()
