"""Pytest configuration and test fixtures."""

import os
import pytest

# Ensure safe testing environment variables
os.environ["BOT_TOKEN"] = "123456789:TEST_MOCK_TOKEN_XYZ"
os.environ["ADMIN_IDS"] = "111222333,999888777"
os.environ["REQUIRED_REFERRALS"] = "3"
os.environ["CLOSED_CHANNEL_LINK"] = "https://t.me/+test_closed_channel"
os.environ["SUBSCRIPTION_CHECK_ENABLED"] = "true"
os.environ["MANDATORY_CHANNELS"] = (
    '[{"name": "Test Channel 1", "url": "https://t.me/test_ch1", "id": -1001111111111}, '
    '{"name": "Test Channel 2", "url": "https://t.me/test_ch2", "id": -1002222222222}]'
)
os.environ["MONGODB_URI"] = "mongodb://localhost:27017"
os.environ["MONGODB_DB_NAME"] = "arab_tili_marathon"
