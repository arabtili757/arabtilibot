"""Referral validation, registration, and notification logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from database.repository import UserRepository

logger = logging.getLogger(__name__)


@dataclass
class ReferralNotification:
    """Represents a notification to be sent to a referrer."""

    kind: str  # 'success', 'progress', 'extra_progress'
    referrer_id: int
    current_count: int
    required_count: int


@dataclass
class RegistrationResult:
    """Result of processing user registration and referral."""

    is_new_user: bool
    user_referrals_count: int
    is_completed: bool
    referrer_notification: Optional[ReferralNotification] = None


class ReferralService:
    """Service encapsulating referral business rules and edge-case handling."""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def process_registration(
        self,
        user_id: int,
        ref_arg: Optional[str | int],
        required_referrals: int,
    ) -> RegistrationResult:
        """Register user once, validate referral, and return notification instructions.

        Edge cases handled:
        - Non-numeric ref_arg: safely rejected
        - Self-referrals: safely rejected
        - Non-existent referrer in DB: safely rejected
        - Repeated registrations: idempotent, preserves referral totals
        - Completion notification on exact threshold and ongoing progress for excess referrals
        """
        existing_user = await self.user_repo.get_user(user_id)

        if existing_user:
            count = int(existing_user.get("referrals_count", 0))
            return RegistrationResult(
                is_new_user=False,
                user_referrals_count=count,
                is_completed=(count >= required_referrals),
                referrer_notification=None,
            )

        # Validate referral argument
        referrer_id: Optional[int] = None
        if ref_arg is not None:
            ref_str = str(ref_arg).strip()
            if ref_str.isdigit():
                candidate = int(ref_str)
                if candidate != user_id:
                    # Referrer must already exist in database
                    if await self.user_repo.user_exists(candidate):
                        referrer_id = candidate

        # Create user record
        await self.user_repo.create_user(user_id=user_id, referrer_id=referrer_id)

        notification: Optional[ReferralNotification] = None

        if referrer_id is not None:
            new_count = await self.user_repo.increment_referrals(referrer_id)
            if new_count == required_referrals:
                notification = ReferralNotification(
                    kind="success",
                    referrer_id=referrer_id,
                    current_count=new_count,
                    required_count=required_referrals,
                )
            elif new_count < required_referrals:
                notification = ReferralNotification(
                    kind="progress",
                    referrer_id=referrer_id,
                    current_count=new_count,
                    required_count=required_referrals,
                )
            else:
                notification = ReferralNotification(
                    kind="extra_progress",
                    referrer_id=referrer_id,
                    current_count=new_count,
                    required_count=required_referrals,
                )

        my_count = await self.user_repo.get_referrals_count(user_id)

        return RegistrationResult(
            is_new_user=True,
            user_referrals_count=my_count,
            is_completed=(my_count >= required_referrals),
            referrer_notification=notification,
        )
