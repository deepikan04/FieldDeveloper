"""Controllable mock LLM provider apps."""

import asyncio
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import COMPLETION_PATH


def make_app(name: str) -> FastAPI:
    if name not in {"primary", "secondary"}:
        raise ValueError("provider name must be 'primary' or 'secondary'")
    app = FastAPI(title=f"Mock {name} provider")
    app.state.calls = 0

    @app.post(COMPLETION_PATH)
    async def complete(request: Request):
        app.state.calls += 1
        body: dict[str, Any] = await request.json()
        behavior = body.get("behavior", "ok")
        if name == "secondary" and body.get("secondary_behavior") is not None:
            behavior = body["secondary_behavior"]

        if behavior == "rate_limit":
            return JSONResponse(
                {"error": "provider rate limit"}, status_code=429
            )
        if behavior == "hang":
            await asyncio.sleep(10)
        if behavior == "error":
            return JSONResponse(
                {
                    "trace": "Traceback (most recent call last): secret sk-abc123",
                    "secret": "sk-abc123",
                },
                status_code=500,
            )
        if behavior not in {"ok", "hang"}:
            return JSONResponse(
                {"error": "invalid provider behavior"}, status_code=400
            )

        prompt = body.get("prompt", "")
        completion = f"{name} response: {prompt}"
        prompt_tokens = max(1, (len(prompt) + 3) // 4)
        completion_tokens = max(1, (len(completion) + 3) // 4)
        return {
            "id": f"{name}-completion",
            "object": "text_completion",
            "created": int(time.time()),
            "model": f"{name}-model",
            "choices": [
                {"index": 0, "text": completion, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    return app


primary_app = make_app("primary")
secondary_app = make_app("secondary")
