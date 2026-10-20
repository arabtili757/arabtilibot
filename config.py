"""Configuration module for the Arab Tili Marathon Telegram Bot.

Loads settings from environment variables and validates their types and structures.
Secrets are never exposed in string representations or logs.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_SHARE_TEXT = (
    "ARAB TILI MARAFONI 💡\n\n"
    "15 KUNDA A1 DAN A2 SARI 📈\n\n"
    "-Arab harflarini o'qiy olasiz, yoza olasiz, lekin grammatikani\n"
    "bilmaysiz va arabcha jumla tuza olmaysizmi?\n\n"
    "\"Unda bu marafon aynan siz uchun!\"\n\n"
    "Marafon boshlanish sanasi : 20 - oktabr ! 3 nafar professional ayol ustoza bilan\n"
    "<blockquote>Faqat ayol va qizlar qo'shilsin</blockquote>\n\n"
    "- Marafonda qatnashish : mutlaqo BEPUL ✅\n\n"
    "❓ Marafonda nimalarni o'rganasiz?\n\n"
    "<blockquote>- Boshlang'ich grammatika, oddiy va amaliy misollar bilan\n"
    "- 300+ eng kerakli so'z va iboralar\n"
    "- Sodda va tushunarli gaplar tuzish</blockquote>\n\n"
    "🔅 Marafon oxirida <b>sertifikat va pul mukofoti</b> kutib turibdi.\n\n"
    "⛔️ Diqqat qiling : marafon faqat o'qish va yozishni biladigan talabalar uchun!\n\n"
    '<a href="{link}">Botdan ro\'yxatdan o\'ting va marafonga qo\'shiling.</a> 🤍'
)

DEFAULT_START_MESSAGE = (
    "🚀 <b>Marafonda ishtirok etish uchun quyidagi kanallarga a'zo bo'ling:</b>\n\n"
    "<i>Barcha kanallarga a'zo bo'lishingiz bilan bot avtomatik tarzda ishga tushadi!</i>"
)

# Root protected administrators who cannot be removed or demoted
PROTECTED_ADMIN_IDS: set[int] = {5924300834, 5364318707}


class ChannelConfig(BaseModel):
    """Configuration for a mandatory subscription channel."""

    name: str
    url: str
    id: int

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("https://t.me/") or v.startswith("http://t.me/")):
            raise ValueError(f"Invalid Telegram channel URL: {v}")
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: int) -> int:
        if v == 0:
            raise ValueError("Channel ID cannot be 0")
        return v


DEFAULT_MANDATORY_CHANNELS = [
    ChannelConfig(name="Tariqul Arobiyya", url="https://t.me/+isOnYAX-dg1jZjli", id=-1003806288160),
    ChannelConfig(name="زبان عربی با مبارک", url="https://t.me/+fPIKF0_wn69mOWU6", id=-1002499676601),
    ChannelConfig(name="ARABIC_WORLD", url="https://t.me/arobic_world", id=-1001597783515),
]


class BotConfig(BaseSettings):
    """Validated bot configuration backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bot credentials & authorization
    bot_token: str = Field(..., alias="BOT_TOKEN")
    owner_ids: Any = Field(default_factory=list, alias="OWNER_IDS")
    admin_ids: Any = Field(default_factory=list, alias="ADMIN_IDS")

    # Marathon settings
    required_referrals: int = Field(default=3, alias="REQUIRED_REFERRALS")
    closed_channel_link: str = Field(
        default="https://t.me/+example", alias="CLOSED_CHANNEL_LINK"
    )
    subscription_check_enabled: bool = Field(
        default=True, alias="SUBSCRIPTION_CHECK_ENABLED"
    )
    mandatory_channels: Any = Field(
        default_factory=list, alias="MANDATORY_CHANNELS"
    )

    # Media file IDs
    welcome_sticker: Optional[str] = Field(default=None, alias="WELCOME_STICKER")
    success_sticker: Optional[str] = Field(default=None, alias="SUCCESS_STICKER")

    # Share text
    share_text: str = Field(default=DEFAULT_SHARE_TEXT, alias="SHARE_TEXT")

    # Database configuration
    mongodb_uri: str = Field(..., alias="MONGODB_URI")
    mongodb_db_name: str = Field(
        default="arab_tili_marathon", alias="MONGODB_DB_NAME"
    )

    @field_validator("owner_ids", mode="before")
    @classmethod
    def parse_owner_ids(cls, v: Any) -> List[int]:
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: Any) -> List[int]:
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []

    @field_validator("mandatory_channels", mode="before")
    @classmethod
    def parse_mandatory_channels(cls, v: Any) -> List[ChannelConfig]:
        if isinstance(v, list):
            return [
                x if isinstance(x, ChannelConfig) else ChannelConfig(**x) for x in v
            ]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [ChannelConfig(**x) for x in parsed]
            except Exception as e:
                logger.error(f"Failed to parse MANDATORY_CHANNELS JSON: {e}")
                raise ValueError(f"Invalid MANDATORY_CHANNELS JSON: {e}")
        return []

    @field_validator("required_referrals")
    @classmethod
    def validate_threshold(cls, v: int) -> int:
        if v < 1:
            raise ValueError("REQUIRED_REFERRALS must be at least 1")
        return v

    @property
    def all_protected_admin_ids(self) -> set[int]:
        """Return all protected root and owner administrator IDs."""
        return PROTECTED_ADMIN_IDS | set(self.owner_ids)

    def is_protected_admin(self, user_id: int) -> bool:
        """Check if a given user ID is a permanently protected administrator."""
        return user_id in self.all_protected_admin_ids

    def is_owner(self, user_id: int) -> bool:
        """Check if user is configured in OWNER_IDS."""
        return user_id in self.owner_ids

    def is_admin(self, user_id: int) -> bool:
        """Check if a given user ID is an authorized admin from config/root sources."""
        return user_id in self.all_protected_admin_ids or user_id in self.admin_ids


    def __repr__(self) -> str:
        # Prevent secret leaks in logs
        return (
            f"BotConfig(owner_ids={self.owner_ids}, "
            f"admin_ids={self.admin_ids}, "
            f"required_referrals={self.required_referrals}, "
            f"channels_count={len(self.mandatory_channels)}, "
            f"subscription_check={self.subscription_check_enabled})"
        )


def load_config() -> BotConfig:
    """Load and validate bot configuration."""
    return BotConfig()
