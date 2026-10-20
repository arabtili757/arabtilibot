"""Filters and security helpers for Telegram handlers."""

from __future__ import annotations

from typing import Any, Optional, Union
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config import BotConfig


async def is_authorized_admin(
    user_id: int, config: BotConfig, settings_repo: Optional[Any] = None
) -> bool:
    """Centralized admin authorization checking protected root IDs, config IDs, and dynamic DB admins."""
    if not user_id:
        return False
    # Fast path: Permanently protected root and owner administrators
    if config.is_protected_admin(user_id):
        return True
    # Dynamic path: Database-managed administrators
    if settings_repo:
        try:
            return await settings_repo.is_admin(user_id, config)
        except Exception:
            return False
    return config.is_admin(user_id)



class IsAdminFilter(BaseFilter):
    """Filter to ensure authorized administrators (protected or dynamic) can invoke handlers."""

    def __init__(
        self, config: BotConfig, settings_repo: Optional[Any] = None
    ) -> None:
        self.config = config
        self.settings_repo = settings_repo

    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        user = event.from_user
        if not user:
            return False
        return await is_authorized_admin(user.id, self.config, self.settings_repo)



class IsOwnerFilter(BaseFilter):
    """Filter ensuring owner administrators can access owner-specific workflows if needed."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        user = event.from_user
        if not user:
            return False
        return self.config.is_owner(user.id)

