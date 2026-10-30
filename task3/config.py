"""Shared streaming gateway constants."""

import os

PROVIDER_URL = os.getenv("LLM_PROVIDER_URL", "http://127.0.0.1:8001")
PROVIDER_STREAM_PATH = "/v1/stream"
GATEWAY_STREAM_PATH = "/v1/stream"
SSE_MEDIA_TYPE = "text/event-stream"
REDACTED = "[REDACTED]"
# Retain a complete email (64-character local part + @ + 253-character
# domain) and boundary context until it can be safely emitted.
HOLDBACK = 320
PROVIDER_CHUNK_SIZE = 7
PROVIDER_CHUNK_DELAY_SECONDS = 0.005
