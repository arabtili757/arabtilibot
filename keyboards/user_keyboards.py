"""Inline keyboards for user interactions and subscription flows."""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import quote
from aiogram import types
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

SHARE_TEXT_PROMPT = "Shu botga kirib ko'ring, zo'r ekan! Arab tili marafoniga qo'shiling!"


def build_share_url(bot_username: str, user_id: int) -> tuple[str, str]:
    """Build personal referral link and native Telegram share URL.

    Returns:
        (my_referral_link, telegram_share_url)
    """
    username = bot_username or "ArabiyaBoost_bot"
    my_link = f"https://t.me/{username}?start={user_id}"
    share_url = (
        f"https://t.me/share/url?url={quote(my_link, safe='')}&text={quote(SHARE_TEXT_PROMPT, safe='')}"
    )
    return my_link, share_url


def get_sub_keyboard(
    channels: List[Any],
    include_check_button: bool = False,
    ref_id: Optional[Any] = None,
) -> InlineKeyboardMarkup:
    """Generate inline keyboard with channel links.

    Manual 'A'zo bo'ldim' button is removed from the normal user experience
    per automatic subscription verification requirements.
    """
    builder = InlineKeyboardBuilder()

    for ch in channels:
        name = ch.name if hasattr(ch, "name") else ch.get("name", "Kanal")
        url = ch.url if hasattr(ch, "url") else ch.get("url", "")
        builder.row(types.InlineKeyboardButton(text=name, url=url))

    if include_check_button:
        cb_data = (
            f"checksub_{ref_id}"
            if ref_id not in (None, "", "none")
            else "checksub_none"
        )
        builder.row(
            types.InlineKeyboardButton(text="✅ A'zo bo'ldim", callback_data=cb_data)
        )

    return builder.as_markup()


def get_share_keyboard(share_url: str) -> InlineKeyboardMarkup:
    """Generate inline keyboard with personal share button."""
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📤 Do'stlarga ulashish",
            url=share_url,
        )
    )
    return builder.as_markup()
