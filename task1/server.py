"""Entrypoint for the stdio MCP server."""

import asyncio

from strict_mcp_server.server import run


if __name__ == "__main__":
    asyncio.run(run())
