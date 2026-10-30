"""Entrypoint for the streaming PII gateway."""

from streaming_pii_gateway.gateway import app, create_app

__all__ = ["app", "create_app"]
