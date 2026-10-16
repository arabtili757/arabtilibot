"""Unit tests for referral validation, registration, and notification edge cases."""

import asyncio
from typing import Any, Dict, List, Optional
import pytest
from services.referral_service import ReferralService


class MockUserRepository:
    """In-memory asynchronous user repository for fast, isolated unit tests."""

    def __init__(self):
        self.users: Dict[int, Dict[str, Any]] = {}

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.users.get(user_id)

    async def user_exists(self, user_id: int) -> bool:
        return user_id in self.users

    async def create_user(
        self, user_id: int, referrer_id: Optional[int] = None
    ) -> Dict[str, Any]:
        if user_id not in self.users:
            self.users[user_id] = {
                "user_id": user_id,
                "referrer_id": referrer_id,
                "referrals_count": 0,
            }
        return self.users[user_id]

    async def increment_referrals(self, referrer_id: int) -> int:
        if referrer_id in self.users:
            self.users[referrer_id]["referrals_count"] += 1
            return self.users[referrer_id]["referrals_count"]
        return 0

    async def get_referrals_count(self, user_id: int) -> int:
        user = self.users.get(user_id)
        return user["referrals_count"] if user else 0


def test_registration_without_referral():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        result = await service.process_registration(
            user_id=1001, ref_arg=None, required_referrals=3
        )

        assert result.is_new_user is True
        assert result.user_referrals_count == 0
        assert result.is_completed is False
        assert result.referrer_notification is None

        user = await repo.get_user(1001)
        assert user is not None
        assert user["referrer_id"] is None
        assert user["referrals_count"] == 0

    asyncio.run(_test())


def test_referral_non_numeric_ignored():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        result = await service.process_registration(
            user_id=1002, ref_arg="invalid_string", required_referrals=3
        )
        assert result.is_new_user is True
        user = await repo.get_user(1002)
        assert user["referrer_id"] is None
        assert result.referrer_notification is None

    asyncio.run(_test())


def test_self_referral_ignored():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        result = await service.process_registration(
            user_id=1003, ref_arg="1003", required_referrals=3
        )
        assert result.is_new_user is True
        user = await repo.get_user(1003)
        assert user["referrer_id"] is None
        assert result.referrer_notification is None

    asyncio.run(_test())


def test_non_existent_referrer_ignored():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        # Referrer 9999 does not exist in DB
        result = await service.process_registration(
            user_id=1004, ref_arg="9999", required_referrals=3
        )
        assert result.is_new_user is True
        user = await repo.get_user(1004)
        assert user["referrer_id"] is None
        assert result.referrer_notification is None

    asyncio.run(_test())


def test_valid_referral_progress_notification():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        # First user joins
        await service.process_registration(user_id=2001, ref_arg=None, required_referrals=3)

        # Second user joins using 2001's referral
        res = await service.process_registration(user_id=2002, ref_arg="2001", required_referrals=3)
        assert res.is_new_user is True
        assert res.referrer_notification is not None
        assert res.referrer_notification.kind == "progress"
        assert res.referrer_notification.referrer_id == 2001
        assert res.referrer_notification.current_count == 1
        assert res.referrer_notification.required_count == 3

        ref_user = await repo.get_user(2001)
        assert ref_user["referrals_count"] == 1

    asyncio.run(_test())


def test_referral_threshold_reached_notification():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        # Referrer registers
        await service.process_registration(user_id=3000, ref_arg=None, required_referrals=3)

        # First referral
        res1 = await service.process_registration(user_id=3001, ref_arg="3000", required_referrals=3)
        assert res1.referrer_notification.kind == "progress"
        assert res1.referrer_notification.current_count == 1

        # Second referral
        res2 = await service.process_registration(user_id=3002, ref_arg="3000", required_referrals=3)
        assert res2.referrer_notification.kind == "progress"
        assert res2.referrer_notification.current_count == 2

        # Third referral reaches threshold (3/3)
        res3 = await service.process_registration(user_id=3003, ref_arg="3000", required_referrals=3)
        assert res3.referrer_notification.kind == "success"
        assert res3.referrer_notification.current_count == 3
        assert res3.referrer_notification.required_count == 3

        # Referrer revisits /start -> should be marked completed
        revisit = await service.process_registration(user_id=3000, ref_arg=None, required_referrals=3)
        assert revisit.is_new_user is False
        assert revisit.is_completed is True
        assert revisit.user_referrals_count == 3

    asyncio.run(_test())


def test_referral_count_exceeding_threshold_progress():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        await service.process_registration(user_id=4000, ref_arg=None, required_referrals=2)
        await service.process_registration(user_id=4001, ref_arg="4000", required_referrals=2)
        await service.process_registration(user_id=4002, ref_arg="4000", required_referrals=2)

        # 3rd referral exceeds threshold of 2
        res = await service.process_registration(user_id=4003, ref_arg="4000", required_referrals=2)
        assert res.referrer_notification.kind == "extra_progress"
        assert res.referrer_notification.current_count == 3

        ref_user = await repo.get_user(4000)
        assert ref_user["referrals_count"] == 3

    asyncio.run(_test())


def test_registration_idempotency():
    async def _test():
        repo = MockUserRepository()
        service = ReferralService(repo)

        await service.process_registration(user_id=5000, ref_arg=None, required_referrals=3)

        # Register user with referral
        res1 = await service.process_registration(user_id=5001, ref_arg="5000", required_referrals=3)
        assert res1.is_new_user is True

        # Register SAME user again with a different referral
        res2 = await service.process_registration(user_id=5001, ref_arg="9999", required_referrals=3)
        assert res2.is_new_user is False
        assert res2.referrer_notification is None

        # Referrer count should NOT have changed on repeated registration
        ref_user = await repo.get_user(5000)
        assert ref_user["referrals_count"] == 1

    asyncio.run(_test())
