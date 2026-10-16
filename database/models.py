"""Data models for MongoDB documents and runtime configuration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return current UTC datetime with timezone awareness."""
    return datetime.now(timezone.utc)


class UserDocument(BaseModel):
    """Represents a user in the MongoDB database."""

    user_id: int
    referrer_id: Optional[int] = None
    referrals_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChannelModel(BaseModel):
    """Represents a mandatory subscription channel."""

    name: str
    url: str
    id: int


class BotSettingsDocument(BaseModel):
    """Dynamic runtime settings stored in MongoDB."""

    key: str = "app_settings"
    required_referrals: int = 3
    closed_channel_link: str
    subscription_check_enabled: bool = True
    mandatory_channels: List[ChannelModel] = Field(default_factory=list)
    share_text: str
    photo_1: Optional[str] = None
    photo_2: Optional[str] = None
    welcome_sticker: Optional[str] = None
    success_sticker: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)
