"""Mock downstream MCP server used by the standalone app."""

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import (
    INVALID_PARAMS_CODE,
    JSONRPC_VERSION,
    MCP_PATH,
    PARSE_ERROR_CODE,
)

admin_reset_key_invocations = 0


def create_downstream_app() -> FastAPI:
    app = FastAPI(title="Mock MCP downstream")

    @app.post(MCP_PATH)
    async def handle_mcp(request: Request) -> JSONResponse:
        global admin_reset_key_invocations
        try:
            message: Any = await request.json()
        except ValueError:
            return JSONResponse(
                {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": None,
                    "error": {"code": PARSE_ERROR_CODE, "message": "Parse error"},
                }
            )

        if not isinstance(message, dict):
            return JSONResponse(
                {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": None,
                    "error": {
                        "code": INVALID_PARAMS_CODE,
                        "message": "Invalid request",
                    },
                }
            )

        request_id = message.get("id")
        method = message.get("method")
        if method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "get_time",
                        "description": "Return the current UTC time.",
                    },
                    {
                        "name": "admin_reset_key",
                        "description": "Reset a key (admin only).",
                    },
                ]
            }
        elif method == "tools/call":
            params = message.get("params")
            if not isinstance(params, dict) or not isinstance(
                params.get("name"), str
            ):
                return JSONResponse(
                    {
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": INVALID_PARAMS_CODE,
                            "message": "Invalid params",
                        },
                    }
                )
            tool_name = params["name"]
            if tool_name == "get_time":
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                }
            elif tool_name == "admin_reset_key":
                admin_reset_key_invocations += 1
                result = {
                    "content": [
                        {"type": "text", "text": "Key reset"}
                    ]
                }
            else:
                return JSONResponse(
                    {
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                )
        else:
            return JSONResponse(
                {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )

        return JSONResponse(
            {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}
        )

    return app


app = create_downstream_app()
