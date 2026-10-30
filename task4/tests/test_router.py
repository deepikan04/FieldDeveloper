"""Tests for SQLite rate limiting and resilient provider routing."""

import asyncio
import sqlite3

import httpx
import pytest
from asgi_lifespan import LifespanManager

from llm_router.gateway import create_app
from llm_router.providers import make_app
from llm_router.rate_limiter import RateLimiter
from llm_router.router import GatewayError, ModelRouter


@pytest.mark.asyncio
async def test_rate_limiter_admission_rejection_and_key_isolation(tmp_path):
    limiter = RateLimiter(tmp_path / "usage.db", budget=100, window_seconds=60)
    admitted = await limiter.reserve("alpha", 60, now=1000)
    assert admitted.admitted
    rejected = await limiter.reserve("alpha", 50, now=1001)
    assert not rejected.admitted
    assert rejected.row_id is None
    other_tenant = await limiter.reserve("beta", 50, now=1001)
    assert other_tenant.admitted
    with sqlite3.connect(tmp_path / "usage.db") as connection:
        recorded = connection.execute(
            "SELECT SUM(tokens) FROM usage WHERE api_key = ?",
            ("alpha",),
        ).fetchone()[0]
    assert recorded == 60


@pytest.mark.asyncio
async def test_sliding_window_eviction_reconcile_and_persistence(tmp_path):
    path = tmp_path / "usage.db"
    limiter = RateLimiter(path, budget=100, window_seconds=60)
    reservation = await limiter.reserve("alpha", 60, now=1000)
    assert reservation.admitted
    await limiter.reconcile(reservation.row_id, 80, now=1001)

    rejected = await limiter.reserve("alpha", 30, now=1002)
    assert not rejected.admitted
    fresh_limiter = RateLimiter(path, budget=100, window_seconds=60)
    still_rejected = await fresh_limiter.reserve("alpha", 30, now=1002)
    assert not still_rejected.admitted

    admitted_after_expiry = await fresh_limiter.reserve("alpha", 100, now=1061)
    assert admitted_after_expiry.admitted


@pytest.mark.asyncio
async def test_concurrent_reservations_are_atomic(tmp_path):
    limiter = RateLimiter(tmp_path / "usage.db", budget=1000, window_seconds=60)
    results = await asyncio.gather(
        *(limiter.reserve("one-key", 30, now=1000) for _ in range(50))
    )
    assert sum(result.admitted for result in results) == 33
    with sqlite3.connect(tmp_path / "usage.db") as connection:
        used_tokens = connection.execute(
            "SELECT SUM(tokens) FROM usage WHERE api_key = ?",
            ("one-key",),
        ).fetchone()[0]
    assert used_tokens == 990


async def _build_router(tmp_path, primary_app, secondary_app, *, timeout=0.5):
    limiter = RateLimiter(tmp_path / "router.db", budget=50_000, window_seconds=60)
    primary_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=primary_app),
        base_url="http://primary",
    )
    secondary_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=secondary_app),
        base_url="http://secondary",
    )
    router = ModelRouter(
        primary_client,
        secondary_client,
        limiter,
        primary_url="http://primary",
        secondary_url="http://secondary",
        timeout_seconds=timeout,
    )
    return router, primary_client, secondary_client


@pytest.mark.asyncio
async def test_429_fails_over_and_both_429s_sanitize_error(tmp_path):
    primary = make_app("primary")
    secondary = make_app("secondary")
    router, primary_client, secondary_client = await _build_router(
        tmp_path, primary, secondary
    )
    try:
        result = await router.complete(
            "Bearer tenant-alpha-key",
            {
                "prompt": "hello",
                "behavior": "rate_limit",
                "secondary_behavior": "ok",
            },
        )
        assert result["failover"] is True
        assert result["model"] == "secondary-model"

        with pytest.raises(GatewayError) as error:
            await router.complete(
                "Bearer tenant-alpha-key",
                {
                    "prompt": "hello",
                    "behavior": "rate_limit",
                    "secondary_behavior": "rate_limit",
                },
            )
        assert error.value.http_status == 502
        assert error.value.code == "all_providers_failed"
    finally:
        await primary_client.aclose()
        await secondary_client.aclose()


@pytest.mark.asyncio
async def test_primary_500_does_not_fail_over_and_error_is_sanitized(tmp_path):
    primary = make_app("primary")
    secondary = make_app("secondary")
    router, primary_client, secondary_client = await _build_router(
        tmp_path, primary, secondary
    )
    try:
        with pytest.raises(GatewayError) as error:
            await router.complete(
                "Bearer tenant-alpha-key",
                {"prompt": "hello", "behavior": "error"},
            )
        assert error.value.http_status == 502
        assert secondary.state.calls == 0
        assert "sk-abc123" not in error.value.message
        assert "Traceback" not in error.value.message
    finally:
        await primary_client.aclose()
        await secondary_client.aclose()


@pytest.mark.asyncio
async def test_timeout_uses_secondary_provider(tmp_path):
    secondary = make_app("secondary")
    limiter = RateLimiter(tmp_path / "timeout.db", budget=50_000)

    class TimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.host == "primary":
                raise httpx.ReadTimeout("primary timed out")
            return await httpx.ASGITransport(app=secondary).handle_async_request(
                request
            )

    transport = TimeoutTransport()
    primary_client = httpx.AsyncClient(transport=transport)
    secondary_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=secondary)
    )
    router = ModelRouter(
        primary_client,
        secondary_client,
        limiter,
        timeout_seconds=0.1,
    )
    try:
        result = await router.complete(
            "Bearer tenant-alpha-key", {"prompt": "timeout test"}
        )
        assert result["failover"] is True
        assert result["model"] == "secondary-model"
    finally:
        await primary_client.aclose()
        await secondary_client.aclose()


@pytest.mark.asyncio
async def test_gateway_auth_validation_and_over_budget_retry_after(tmp_path):
    primary = make_app("primary")
    secondary = make_app("secondary")
    app = create_app(
        limiter=RateLimiter(tmp_path / "api.db", budget=4, window_seconds=60),
        primary_transport=httpx.ASGITransport(app=primary),
        secondary_transport=httpx.ASGITransport(app=secondary),
        primary_url="http://primary",
        secondary_url="http://secondary",
    )
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            missing = await client.post("/v1/complete", json={"prompt": "test"})
            assert missing.status_code == 401
            bad = await client.post(
                "/v1/complete",
                headers={"Authorization": "Bearer invalid"},
                json={"prompt": "test"},
            )
            assert bad.status_code == 401
            no_prompt = await client.post(
                "/v1/complete",
                headers={"Authorization": "Bearer tenant-alpha-key"},
                json={},
            )
            assert no_prompt.status_code == 400

            upstream_error = await client.post(
                "/v1/complete",
                headers={"Authorization": "Bearer tenant-alpha-key"},
                json={"prompt": "hello", "behavior": "error"},
            )
            assert upstream_error.status_code == 502
            assert "sk-abc123" not in upstream_error.text
            assert "Traceback" not in upstream_error.text

            too_many = await client.post(
                "/v1/complete",
                headers={"Authorization": "Bearer tenant-alpha-key"},
                json={"prompt": "a prompt longer than four tokens"},
            )
            assert too_many.status_code == 429
            assert too_many.json()["error"]["code"] == "rate_limited"
            assert int(too_many.headers["Retry-After"]) > 0
