"""Unit and integration tests for streaming PII redaction."""

import json
import socket
import threading
import time
import httpx
import pytest
import uvicorn
from asgi_lifespan import LifespanManager

from config import HOLDBACK
from streaming_pii_gateway.gateway import create_app
from streaming_pii_gateway.provider import create_provider_app
from streaming_pii_gateway.redactor import StreamRedactor, redact_text


EMAIL_REGRESSIONS = [
    "jane@verylongcompanyname.com",
    "jane@example.technology",
    "a" * 33 + "@example.com",
    "first.last+tag@support.eu.verylongcompanyname.technology",
    "a" * 64 + "@" + ".".join(["b" * 63] * 3 + ["c" * 61]),
]


@pytest.mark.parametrize("email", EMAIL_REGRESSIONS)
@pytest.mark.parametrize("chunk_size", [1, 7, 64, 321, 4096])
def test_long_emails_are_redacted_across_stream_boundaries(email, chunk_size):
    # Long surrounding text forces emission while the email is arriving.
    prefix = "Safe text. " * 40
    suffix = ". Thank you! " * 40
    text = prefix + email + suffix
    expected = prefix + "[REDACTED]" + suffix
    assert redact_text(text) == expected
    redactor = StreamRedactor()
    output = []
    for offset in range(0, len(text), chunk_size):
        output.append(redactor.feed(text[offset : offset + chunk_size]))
        assert len(redactor.buffer) <= 2 * HOLDBACK
    output.append(redactor.flush())
    assert "".join(output) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Email jane@example.com!", "Email [REDACTED]!"),
        ("SSN 123-45-6789.", "SSN [REDACTED]."),
        ("Card 4111 1111 1111 1111!", "Card [REDACTED]!"),
        ("No personal data here.", "No personal data here."),
    ],
)
def test_redacts_patterns_and_preserves_clean_text(text, expected):
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Reach user@host.com, then call 123-45-6789.",
        "Card 4111-1111-1111-1111 and email a.b+tag@example.co.uk",
        "Use 378282246310005 for payment.",
        "Nothing sensitive in this sentence.",
        "prefix user@host.co" + "m suffix",
    ],
)
def test_single_character_feeding_is_chunk_invariant(text):
    redactor = StreamRedactor()
    output = "".join(redactor.feed(character) for character in text)
    output += redactor.flush()
    assert output == redact_text(text)


def test_pii_split_across_two_deltas_is_redacted():
    redactor = StreamRedactor()
    output = redactor.feed("Contact jane.doe@example.")
    output += redactor.feed("com today")
    output += redactor.flush()
    assert output == "Contact [REDACTED] today"


def test_buffer_is_bounded_for_long_pii_saturated_stream():
    redactor = StreamRedactor()
    text = ("a@example.com 123-45-6789 4111111111111111 " * 1000)
    for offset in range(0, len(text), 5):
        redactor.feed(text[offset : offset + 5])
        assert len(redactor.buffer) <= 2 * HOLDBACK


@pytest.mark.asyncio
async def test_gateway_redacts_in_process_provider_responses():
    provider_app = create_provider_app()
    gateway_app = create_app(
        transport=httpx.ASGITransport(app=provider_app),
        provider_url="http://provider",
    )
    async with LifespanManager(gateway_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway_app),
            base_url="http://gateway",
        ) as client:
            pii = await client.post("/v1/stream", json={"inject": "pii"})
            pii_frames = _parse_sse(pii.text)
            pii_text = "".join(pii_frames)
            assert "[REDACTED]" in pii_text
            assert "jane.doe@example.com" not in pii_text
            assert "123-45-6789" not in pii_text
            assert "4111 1111 1111 1111" not in pii_text

            clean_text = "A completely clean paragraph passes unchanged."
            clean = await client.post(
                "/v1/stream", json={"text": clean_text}
            )
            assert "".join(_parse_sse(clean.text)) == clean_text

            custom_text = (
                "Edges: jane@example.com; 123-45-6789; "
                "4111-1111-1111-1111. done"
            )
            custom = await client.post(
                "/v1/stream", json={"text": custom_text}
            )
            custom_output = "".join(_parse_sse(custom.text))
            assert custom_output == "Edges: [REDACTED]; [REDACTED]; [REDACTED]. done"
            assert custom_output.count("[REDACTED]") == 3

            for email in EMAIL_REGRESSIONS:
                response = await client.post(
                    "/v1/stream", json={"text": f"Contact {email}. Thanks!"}
                )
                assert response.status_code == 200
                assert "".join(_parse_sse(response.text)) == (
                    "Contact [REDACTED]. Thanks!"
                )


def _parse_sse(payload: str) -> list[str]:
    content: list[str] = []
    for line in payload.splitlines():
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            continue
        event = json.loads(data)
        content.append(event["choices"][0]["delta"]["content"])
    return content


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RunningServer:
    def __init__(self, app, port: int) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="error",
                lifespan="on",
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError("uvicorn server failed to start")
            time.sleep(0.01)
        raise TimeoutError("uvicorn server did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def test_real_socket_streams_before_provider_finishes():
    provider_port = _free_port()
    gateway_port = _free_port()
    provider = RunningServer(create_provider_app(), provider_port)
    gateway = RunningServer(
        create_app(provider_url=f"http://127.0.0.1:{provider_port}"),
        gateway_port,
    )
    try:
        long_text = ("Streaming response begins safely. " * 60) + "FINAL"
        with httpx.Client(timeout=10) as client:
            first_content_at = None
            done_at = None
            started_at = time.monotonic()
            with client.stream(
                "POST",
                f"http://127.0.0.1:{gateway_port}/v1/stream",
                json={"text": long_text},
            ) as response:
                assert response.status_code == 200
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        done_at = time.monotonic()
                        break
                    if first_content_at is None:
                        first_content_at = time.monotonic()
                        first_payload = json.loads(data)
                        assert first_payload["choices"][0]["delta"]["content"]

            assert first_content_at is not None
            assert done_at is not None
            assert done_at - first_content_at > 0.1
            assert first_content_at - started_at < done_at - started_at
    finally:
        gateway.stop()
        provider.stop()
