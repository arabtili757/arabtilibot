"""Tests for admin authorization, security filters, and broadcast locking."""

import asyncio
from unittest.mock import MagicMock
import pytest
from config import BotConfig
from handlers.middlewares import IsAdminFilter
from services.broadcast_service import BroadcastService


def test_admin_filter_allows_authorized_admin():
    async def _test():
        config = BotConfig(BOT_TOKEN="1:x", ADMIN_IDS="100,200")
        admin_filter = IsAdminFilter(config)

        event = MagicMock()
        event.from_user.id = 100
        assert await admin_filter(event) is True

        event.from_user.id = 200
        assert await admin_filter(event) is True

    asyncio.run(_test())


def test_admin_filter_rejects_unauthorized_user():
    async def _test():
        config = BotConfig(BOT_TOKEN="1:x", ADMIN_IDS="100,200")
        admin_filter = IsAdminFilter(config)

        event = MagicMock()
        event.from_user.id = 999
        assert await admin_filter(event) is False

    asyncio.run(_test())


def test_admin_filter_handles_missing_user():
    async def _test():
        config = BotConfig(BOT_TOKEN="1:x", ADMIN_IDS="100")
        admin_filter = IsAdminFilter(config)

        event = MagicMock()
        event.from_user = None
        assert await admin_filter(event) is False

    asyncio.run(_test())


def test_broadcast_service_prevents_concurrent_runs():
    async def _test():
        service = BroadcastService()
        bot = MagicMock()

        # Simulate broadcast starting
        async with service._lock:
            service._is_running = True

        with pytest.raises(RuntimeError, match="Another broadcast is already in progress"):
            await service.broadcast_message(
                bot=bot,
                user_ids=[1, 2, 3],
                from_chat_id=10,
                message_id=20,
            )

    asyncio.run(_test())
