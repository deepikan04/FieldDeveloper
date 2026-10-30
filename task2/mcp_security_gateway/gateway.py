"""Authenticated JSON-RPC proxy app."""

import json
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from config import (
    DOWNSTREAM_URL,
    INVALID_PARAMS_CODE,
    INVALID_REQUEST_CODE,
    JSONRPC_VERSION,
    MCP_PATH,
    PARSE_ERROR_CODE,
    TOKEN_ROLES,
    UNAUTHORIZED_CODE,
)


def _rpc_error(code: int, message: str, request_id: Any = None) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def _role_from_authorization(value: str | None) -> str | None:
    if value is None:
        return None
    scheme, separator, token = value.partition(" ")
    if scheme != "Bearer" or not separator or not token or " " in token:
        return None
    return TOKEN_ROLES.get(token)


def create_app(transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(
            base_url=DOWNSTREAM_URL,
            transport=transport,
        ) as client:
            app.state.downstream_client = client
            yield

    app = FastAPI(title="MCP Security Gateway", lifespan=lifespan)

    @app.post(MCP_PATH)
    async def proxy(request: Request) -> Response:
        role = _role_from_authorization(request.headers.get("authorization"))
        if role is None:
            return _rpc_error(UNAUTHORIZED_CODE, "Unauthorized")

        raw_body = await request.body()
        try:
            message: Any = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _rpc_error(PARSE_ERROR_CODE, "Parse error")

        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != JSONRPC_VERSION
            or not isinstance(message.get("method"), str)
            or not message["method"]
            or ("id" in message and isinstance(message["id"], (dict, list, bool)))
            or (
                "params" in message
                and not isinstance(message["params"], (dict, list))
            )
        ):
            request_id = message.get("id") if isinstance(message, dict) else None
            return _rpc_error(INVALID_REQUEST_CODE, "Invalid Request", request_id)

        if message["method"] == "tools/call":
            params = message.get("params")
            if not isinstance(params, dict) or not isinstance(
                params.get("name"), str
            ):
                return _rpc_error(
                    INVALID_PARAMS_CODE, "Invalid params", message.get("id")
                )
            if params["name"].startswith("admin_") and role != "admin":
                return _rpc_error(
                    UNAUTHORIZED_CODE,
                    "Unauthorized Tool Call",
                    message.get("id"),
                )

        downstream_response = await request.app.state.downstream_client.post(
            MCP_PATH,
            content=raw_body,
            headers={"content-type": "application/json"},
        )
        return Response(
            content=downstream_response.content,
            status_code=downstream_response.status_code,
            headers={
                key: value
                for key, value in downstream_response.headers.items()
                if key.lower() == "content-type"
            },
        )

    return app


app = create_app()
