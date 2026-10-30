"""Small OpenAI-style SSE provider for local execution and tests."""

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from config import (
    PROVIDER_CHUNK_DELAY_SECONDS,
    PROVIDER_CHUNK_SIZE,
    PROVIDER_STREAM_PATH,
    SSE_MEDIA_TYPE,
)

PII_SAMPLE = (
    "Contact jane.doe@example.com, SSN 123-45-6789, "
    "or card 4111 1111 1111 1111 for help."
)


def create_provider_app() -> FastAPI:
    app = FastAPI(title="Mock LLM provider")

    @app.post(PROVIDER_STREAM_PATH)
    async def stream(request: Request) -> StreamingResponse:
        body: dict[str, Any] = await request.json()
        if isinstance(body.get("text"), str):
            text = body["text"]
        elif body.get("inject") == "pii":
            text = PII_SAMPLE
        else:
            text = "This is a clean response with no personal information."

        async def events():
            for offset in range(0, len(text), PROVIDER_CHUNK_SIZE):
                piece = text[offset : offset + PROVIDER_CHUNK_SIZE]
                payload = json.dumps(
                    {"choices": [{"delta": {"content": piece}}]}
                )
                yield f"data: {payload}\n\n"
                await asyncio.sleep(PROVIDER_CHUNK_DELAY_SECONDS)
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type=SSE_MEDIA_TYPE)

    return app


app = create_provider_app()
