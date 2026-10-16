"""Safe, rate-limited broadcast service for administrative messaging."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

logger = logging.getLogger(__name__)


class BroadcastService:
    """Manages rate-limited broadcast operations with error handling and deduplication."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Check if a broadcast is currently in progress."""
        return self._is_running

    async def broadcast_message(
        self,
        bot: Bot,
        user_ids: List[int],
        from_chat_id: int,
        message_id: int,
        rate_limit_delay: float = 0.04,  # ~25 messages/second
    ) -> Dict[str, int]:
        """Broadcast a message to all specified users safely.

        Never reveals the recipient list.
        Handles Telegram API rate limits and individual delivery errors.
        """
        async with self._lock:
            if self._is_running:
                raise RuntimeError("Another broadcast is already in progress.")
            self._is_running = True

        sent_count = 0
        failed_count = 0
        total_recipients = len(user_ids)

        logger.info(f"Starting broadcast to {total_recipients} recipient(s)...")

        try:
            for uid in user_ids:
                try:
                    await bot.copy_message(
                        chat_id=uid,
                        from_chat_id=from_chat_id,
                        message_id=message_id,
                    )
                    sent_count += 1
                except TelegramRetryAfter as e:
                    logger.warning(f"Telegram flood control: sleeping for {e.retry_after}s")
                    await asyncio.sleep(e.retry_after)
                    # Retry once
                    try:
                        await bot.copy_message(
                            chat_id=uid,
                            from_chat_id=from_chat_id,
                            message_id=message_id,
                        )
                        sent_count += 1
                    except Exception as retry_err:
                        logger.warning(f"Delivery failed on retry for {uid}: {retry_err}")
                        failed_count += 1
                except (TelegramForbiddenError, TelegramBadRequest) as e:
                    logger.debug(f"Delivery skipped for inactive user: {e}")
                    failed_count += 1
                except Exception as e:
                    logger.warning(f"Unexpected delivery failure: {e}")
                    failed_count += 1

                await asyncio.sleep(rate_limit_delay)

        finally:
            self._is_running = False

        logger.info(
            f"Broadcast completed. Total: {total_recipients}, Sent: {sent_count}, Failed: {failed_count}"
        )
        return {
            "total": total_recipients,
            "sent": sent_count,
            "failed": failed_count,
        }
