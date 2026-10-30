"""Entrypoint for the completion gateway."""

from llm_router.gateway import app, create_app

__all__ = ["app", "create_app"]
