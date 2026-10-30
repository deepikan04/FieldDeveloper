"""Entrypoint for the mock streaming provider."""

from streaming_pii_gateway.provider import app, create_provider_app

__all__ = ["app", "create_provider_app"]
