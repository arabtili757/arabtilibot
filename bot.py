"""Application entry point for the Arab Tili Marathon Telegram Bot.

Initializes configuration, database connections, routers, and polling.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from database.connection import DatabaseManager
from database.repository import SettingsRepository, UserRepository
from handlers.admin_handlers import create_admin_router
from handlers.user_handlers import create_user_router
from services.broadcast_service import BroadcastService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("arab_tili_bot")


async def main() -> None:
    """Initialize dependencies and start the bot polling loop."""
    config = load_config()
    logger.info("Configuration successfully loaded.")

    if not config.mongodb_uri or not config.mongodb_uri.strip():
        logger.error("MONGODB_URI is required. MongoDB Atlas is the only database.")
        sys.exit(1)

    logger.info("Connecting to MongoDB Atlas...")
    try:
        db_manager = DatabaseManager(config.mongodb_uri, config.mongodb_db_name)
        db = await db_manager.connect()
        user_repo = UserRepository(db)
        settings_repo = SettingsRepository(db)
        logger.info("MongoDB Atlas connected and repositories initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB Atlas: {e}")
        sys.exit(1)

    broadcast_service = BroadcastService()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register modular routers
    admin_router = create_admin_router(
        config=config,
        user_repo=user_repo,
        settings_repo=settings_repo,
        broadcast_service=broadcast_service,
    )
    user_router = create_user_router(
        config=config,
        user_repo=user_repo,
        settings_repo=settings_repo,
    )

    dp.include_router(admin_router)
    dp.include_router(user_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        bot_user = await bot.get_me()
        logger.info(f"Bot @{bot_user.username} started successfully.")
        await dp.start_polling(bot)
    finally:
        if db_manager:
            await db_manager.close()
        await bot.session.close()
        logger.info("Bot stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution terminated.")