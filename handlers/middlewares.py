"""Filters and security helpers for Telegram handlers."""

from __future__ import annotations

from typing import Union
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config import BotConfig


class IsAdminFilter(BaseFilter):
    """Filter to ensure only authorized administrators can invoke protected handlers."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        user = event.from_user
        if not user:
            return False
        return self.config.is_admin(user.id)
