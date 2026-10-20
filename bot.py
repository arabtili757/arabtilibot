"""Application entry point for the Arab Tili Marathon Telegram Bot.

Initializes configuration, database connections, routers, and polling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from aiohttp import web
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
from services.statistics_service import StatisticsService

# Unbuffer output for real-time logs in cloud platforms (Render, Docker)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("arab_tili_bot")


async def health_check_handler(request: web.Request) -> web.Response:
    """Minimal HTTP health check endpoint for Render Web Service."""
    return web.json_response({
        "status": "ok",
        "service": "arab_tili_marathon_bot",
    })


async def start_http_server(host: str = "0.0.0.0", port: int = 10000) -> web.AppRunner:
    """Start non-blocking HTTP server for Render port binding and health checks."""
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"HTTP health server successfully listening on {host}:{port}")
    return runner


async def main() -> None:
    """Initialize dependencies and start the bot polling loop."""
    # 1. Start HTTP health check server immediately so Render detects the port right away
    port = int(os.getenv("PORT", "10000"))
    logger.info(f"Starting HTTP health server on port {port}...")
    http_runner = await start_http_server(host="0.0.0.0", port=port)

    # 2. Load configuration safely
    try:
        config = load_config()
        logger.info("Configuration successfully loaded.")
    except Exception as e:
        logger.error(f"❌ Configuration error: {e}")
        logger.error(
            "Please configure required environment variables in Render Dashboard -> Environment:\n"
            "- BOT_TOKEN\n"
            "- MONGODB_URI\n"
            "- ADMIN_IDS\n"
            "- CLOSED_CHANNEL_LINK\n"
            "- MANDATORY_CHANNELS"
        )
        while True:
            await asyncio.sleep(3600)

    # 3. Connect to MongoDB Atlas (with retry for Atlas IP propagation)
    db_manager = DatabaseManager(config.mongodb_uri, config.mongodb_db_name)
    user_repo = None
    settings_repo = None
    max_retries = 30
    retry_delay = 10

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Connecting to MongoDB Atlas (attempt {attempt}/{max_retries})...")
            db = await db_manager.connect()
            user_repo = UserRepository(db)
            settings_repo = SettingsRepository(db)
            logger.info("MongoDB Atlas connected and repositories initialized successfully.")
            break
        except Exception as e:
            logger.error(f"❌ Failed to connect to MongoDB Atlas (attempt {attempt}/{max_retries}): {e}")
            logger.error(
                "ACTION REQUIRED: In MongoDB Atlas (cloud.mongodb.com), go to Security -> Network Access -> "
                "Add IP Address -> choose 'Allow Access from Anywhere' (0.0.0.0/0)."
            )
            if attempt < max_retries:
                logger.info(f"Waiting {retry_delay}s before retrying MongoDB Atlas connection...")
                await asyncio.sleep(retry_delay)
            else:
                logger.critical("❌ All MongoDB connection attempts failed. HTTP server will remain active.")
                while True:
                    await asyncio.sleep(3600)

    # 4. Start Telegram bot
    broadcast_service = BroadcastService()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    statistics_service = StatisticsService(user_repo, settings_repo)
    admin_router = create_admin_router(
        config=config,
        user_repo=user_repo,
        settings_repo=settings_repo,
        broadcast_service=broadcast_service,
        statistics_service=statistics_service,
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
        allowed_updates = ["message", "callback_query", "chat_member"]
        logger.info(
            f"Bot @{bot_user.username} started successfully with allowed_updates={allowed_updates}."
        )
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        await http_runner.cleanup()
        if db_manager:
            await db_manager.close()
        await bot.session.close()
        logger.info("Bot stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution terminated.")