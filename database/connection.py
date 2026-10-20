"""MongoDB connection and lifecycle management using Motor."""

from __future__ import annotations

import logging
import re
from typing import Optional
import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import pymongo

logger = logging.getLogger(__name__)


def normalize_mongo_uri(uri: str) -> str:
    """Normalize MongoDB URI by removing invalid slashes before query parameters."""
    if not uri:
        return uri
    # Fix e.g. /dbname/?params -> /dbname?params
    return re.sub(r"/([^/?]+)/\?", r"/\1?", uri.strip())


class DatabaseManager:
    """Manages MongoDB connections, indexing, and lifecycle."""

    def __init__(self, uri: str, db_name: str) -> None:
        self.uri = normalize_mongo_uri(uri)
        self.db_name = db_name
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None

    async def connect(self) -> AsyncIOMotorDatabase:
        """Establish connection to MongoDB and ensure indexes."""
        if not self.uri:
            raise ValueError("MongoDB URI is not configured.")

        logger.info("Connecting to MongoDB...")
        if self.client:
            self.client.close()
        self.client = AsyncIOMotorClient(
            self.uri,
            serverSelectionTimeoutMS=5000,
            tlsCAFile=certifi.where(),
        )
        # Test connection
        await self.client.admin.command("ping")
        self.db = self.client[self.db_name]

        await self._ensure_indexes()
        logger.info("Connected to MongoDB successfully and verified indexes.")
        return self.db

    async def _ensure_indexes(self) -> None:
        """Create necessary indexes for performance and data integrity."""
        if self.db is None:
            return

        # Users collection indexes
        users = self.db["users"]
        await users.create_index([("user_id", pymongo.ASCENDING)], unique=True)
        await users.create_index([("status", pymongo.ASCENDING)])
        await users.create_index([("registered_at", pymongo.ASCENDING)])
        await users.create_index([("referrer_id", pymongo.ASCENDING)])
        await users.create_index([("referrals_count", pymongo.DESCENDING)])

        # Settings collection index
        settings = self.db["settings"]
        await settings.create_index([("key", pymongo.ASCENDING)], unique=True)

    async def close(self) -> None:
        """Close MongoDB connection gracefully."""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            logger.info("MongoDB connection closed.")
