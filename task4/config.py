"""Shared router, rate-limit, and provider constants."""

import os

API_KEYS = {
    "tenant-alpha-key": "tenant-alpha",
    "tenant-beta-key": "tenant-beta",
}
DATABASE_PATH = os.getenv("GATEWAY_DB_PATH", "gateway.db")
TOKEN_BUDGET = 50_000
WINDOW_SECONDS = 60
PRIMARY_PROVIDER_URL = os.getenv(
    "PRIMARY_PROVIDER_URL", "http://127.0.0.1:8001"
)
SECONDARY_PROVIDER_URL = os.getenv(
    "SECONDARY_PROVIDER_URL", "http://127.0.0.1:8002"
)
PROVIDER_TIMEOUT_SECONDS = 3.0
COMPLETION_PATH = "/v1/complete"
