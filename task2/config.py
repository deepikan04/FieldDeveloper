"""Shared gateway and mock-server constants."""

import os

TOKEN_ROLES = {
    "viewer-token": "viewer",
    "admin-token": "admin",
}
DOWNSTREAM_URL = os.getenv("MCP_DOWNSTREAM_URL", "http://127.0.0.1:8001")
MCP_PATH = "/mcp"
JSONRPC_VERSION = "2.0"
UNAUTHORIZED_CODE = -32001
PARSE_ERROR_CODE = -32700
INVALID_REQUEST_CODE = -32600
INVALID_PARAMS_CODE = -32602
