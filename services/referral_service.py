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

    async def save_pending_registration(
        self,
        user_id: int,
        ref_arg: Optional[str | int],
    ) -> Dict[str, Any]:
        """Save user as pending registration while preserving referral parameter."""
        existing_user = await self.user_repo.get_user(user_id)
        if existing_user:
            return existing_user

        # Validate candidate referrer
        candidate_referrer_id: Optional[int] = None
        if ref_arg is not None:
            ref_str = str(ref_arg).strip()
            if ref_str.isdigit():
                candidate = int(ref_str)
                if candidate != user_id:
                    # Referrer must exist in database
                    if await self.user_repo.user_exists(candidate):
                        candidate_referrer_id = candidate

        if hasattr(self.user_repo, "save_pending_user"):
            _, user = await self.user_repo.save_pending_user(
                user_id=user_id,
                pending_referrer_id=candidate_referrer_id,
            )
            return user
        else:
            return await self.user_repo.create_user(
                user_id=user_id, referrer_id=candidate_referrer_id
            )

    async def complete_registration(
        self,
        user_id: int,
        required_referrals: int,
    ) -> RegistrationResult:
        """Atomically complete pending registration and credit referrer if applicable."""
        user = await self.user_repo.get_user(user_id)
        if not user:
            # If user does not exist, save pending first
            user = await self.save_pending_registration(user_id=user_id, ref_arg=None)

        if user.get("status") != "pending":
            # Already completed
            count = int(user.get("referrals_count", 0))
            return RegistrationResult(
                is_new_user=False,
                user_referrals_count=count,
                is_completed=(count >= required_referrals),
                referrer_notification=None,
            )

        # Pending user completing registration
        pending_ref = user.get("pending_referrer_id", user.get("referrer_id"))
        referrer_id: Optional[int] = None
        if pending_ref is not None:
            if pending_ref != user_id and await self.user_repo.user_exists(pending_ref):
                referrer_id = pending_ref

        if hasattr(self.user_repo, "complete_user_registration"):
            just_completed, updated_user = await self.user_repo.complete_user_registration(
                user_id=user_id,
                referrer_id=referrer_id,
            )
        else:
            just_completed = True
            updated_user = user

        if not just_completed:
            count = int(updated_user.get("referrals_count", 0))
            return RegistrationResult(
                is_new_user=False,
                user_referrals_count=count,
                is_completed=(count >= required_referrals),
                referrer_notification=None,
            )

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

    async def process_registration(
        self,
        user_id: int,
        ref_arg: Optional[str | int],
        required_referrals: int,
    ) -> RegistrationResult:
        """One-step registration for backward compatibility."""
        await self.save_pending_registration(user_id=user_id, ref_arg=ref_arg)
        return await self.complete_registration(
            user_id=user_id, required_referrals=required_referrals
        )
