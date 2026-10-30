"""FastAPI completion endpoint wiring limiter and provider router."""

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import (
    COMPLETION_PATH,
    DATABASE_PATH,
    PRIMARY_PROVIDER_URL,
    SECONDARY_PROVIDER_URL,
)
from llm_router.rate_limiter import RateLimiter
from llm_router.router import GatewayError, ModelRouter

logger = logging.getLogger(__name__)


def create_app(
    *,
    limiter: RateLimiter | None = None,
    primary_transport: httpx.AsyncBaseTransport | None = None,
    secondary_transport: httpx.AsyncBaseTransport | None = None,
    primary_url: str = PRIMARY_PROVIDER_URL,
    secondary_url: str = SECONDARY_PROVIDER_URL,
) -> FastAPI:
    active_limiter = limiter or RateLimiter(DATABASE_PATH)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with (
            httpx.AsyncClient(transport=primary_transport) as primary_client,
            httpx.AsyncClient(transport=secondary_transport) as secondary_client,
        ):
            app.state.router = ModelRouter(
                primary_client,
                secondary_client,
                active_limiter,
                primary_url=primary_url,
                secondary_url=secondary_url,
            )
            yield

    app = FastAPI(title="Rate-Limited Model Gateway", lifespan=lifespan)

    @app.post(COMPLETION_PATH)
    async def complete(request: Request):
        try:
            body: Any = await request.json()
            if not isinstance(body, dict):
                raise GatewayError(
                    "invalid_request", "A JSON object is required", 400
                )
            result = await request.app.state.router.complete(
                request.headers.get("authorization"), body
            )
            return JSONResponse(result)
        except GatewayError as exc:
            headers = {}
            if exc.retry_after is not None:
                headers["Retry-After"] = str(exc.retry_after)
            return JSONResponse(
                {"error": {"code": exc.code, "message": exc.message}},
                status_code=exc.http_status,
                headers=headers,
            )
        except json.JSONDecodeError:
            return JSONResponse(
                {
                    "error": {
                        "code": "invalid_request",
                        "message": "Malformed JSON",
                    }
                },
                status_code=400,
            )
        except Exception:
            logger.exception("Unexpected completion gateway error")
            return JSONResponse(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "An internal error occurred",
                    }
                },
                status_code=500,
            )

    return app


app = create_app()
