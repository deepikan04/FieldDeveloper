"""Entrypoint for the MCP security gateway."""

from mcp_security_gateway.gateway import app, create_app

__all__ = ["app", "create_app"]
