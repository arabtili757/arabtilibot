"""Safe Telegram message sending utilities with error handling."""

from __future__ import annotations

import logging
from typing import Any, List, Optional
from aiogram import Bot
from aiogram.types import InputMediaPhoto, LinkPreviewOptions, Message

logger = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def safe_send(
    bot: Bot, chat_id: int, text: str, **kwargs: Any
) -> Optional[Message]:
    """Safely send a Telegram message catching exceptions to prevent crashes."""
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.warning(f"Could not send message to {chat_id}: {e}")
        return None


async def safe_sticker(
    bot: Bot, chat_id: int, sticker: Optional[str]
) -> Optional[Message]:
    """Safely send a Telegram sticker."""
    if not sticker or not sticker.strip():
        return None
    try:
        return await bot.send_sticker(chat_id, sticker)
    except Exception as e:
        logger.warning(f"Could not send sticker to {chat_id}: {e}")
        return None


async def safe_send_media_group(
    bot: Bot, chat_id: int, media: List[InputMediaPhoto]
) -> Optional[List[Message]]:
    """Safely send a media group with error handling."""
    try:
        return await bot.send_media_group(chat_id=chat_id, media=media)
    except Exception as e:
        logger.warning(f"Media group delivery failed for {chat_id}: {e}")
        return None


async def safe_send_photo(
    bot: Bot,
    chat_id: int,
    photo: str,
    caption: Optional[str] = None,
    **kwargs: Any,
) -> Optional[Message]:
    """Safely send a Telegram photo catching exceptions to prevent crashes."""
    try:
        return await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, **kwargs)
    except Exception as e:
        logger.warning(f"Could not send photo to {chat_id}: {e}")
        return None

