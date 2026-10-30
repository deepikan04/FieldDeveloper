"""Streaming proxy that redacts provider deltas before sending them onward."""

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from config import (
    GATEWAY_STREAM_PATH,
    PROVIDER_STREAM_PATH,
    PROVIDER_URL,
    SSE_MEDIA_TYPE,
)
from streaming_pii_gateway.redactor import StreamRedactor


def create_app(
    transport: httpx.AsyncBaseTransport | None = None,
    provider_url: str = PROVIDER_URL,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(
            base_url=provider_url,
            transport=transport,
            timeout=None,
        ) as client:
            app.state.provider_client = client
            yield

    app = FastAPI(title="Streaming PII Gateway", lifespan=lifespan)

    @app.post(GATEWAY_STREAM_PATH)
    async def stream(request: Request) -> StreamingResponse:
        body: Any = await request.json()
        client: httpx.AsyncClient = request.app.state.provider_client

        async def output_events() -> AsyncIterator[str]:
            redactor = StreamRedactor()
            async with client.stream(
                "POST", PROVIDER_STREAM_PATH, json=body
            ) as upstream:
                upstream.raise_for_status()
                data_lines: list[str] = []
                async for line in upstream.aiter_lines():
                    if line == "":
                        if not data_lines:
                            continue
                        data = "\n".join(data_lines)
                        data_lines.clear()
                        if data == "[DONE]":
                            final_text = redactor.flush()
                            if final_text:
                                yield _sse_delta(final_text)
                            yield "data: [DONE]\n\n"
                            return
                        try:
                            event: dict[str, Any] = json.loads(data)
                            content = event["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            continue
                        if isinstance(content, str):
                            safe_text = redactor.feed(content)
                            if safe_text:
                                yield _sse_delta(safe_text)
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

            final_text = redactor.flush()
            if final_text:
                yield _sse_delta(final_text)
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            output_events(),
            media_type=SSE_MEDIA_TYPE,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _sse_delta(text: str) -> str:
    payload = json.dumps({"choices": [{"delta": {"content": text}}]})
    return f"data: {payload}\n\n"


app = create_app()
