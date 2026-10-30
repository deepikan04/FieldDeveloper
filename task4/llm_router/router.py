"""Authenticated provider routing with safe, bounded fallback behavior."""

import asyncio
import logging
from typing import Any

import httpx

from config import (
    API_KEYS,
    COMPLETION_PATH,
    PROVIDER_TIMEOUT_SECONDS,
)
from llm_router.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int,
        *,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after


class ModelRouter:
    def __init__(
        self,
        primary_client: httpx.AsyncClient,
        secondary_client: httpx.AsyncClient,
        limiter: RateLimiter,
        *,
        primary_url: str = "http://primary",
        secondary_url: str = "http://secondary",
        timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        self.primary_client = primary_client
        self.secondary_client = secondary_client
        self.limiter = limiter
        self.primary_url = primary_url
        self.secondary_url = secondary_url
        self.timeout_seconds = timeout_seconds

    async def complete(
        self, authorization: str | None, body: dict[str, Any]
    ) -> dict[str, Any]:
        api_key = self._authenticate(authorization)
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise GatewayError("invalid_request", "A prompt is required", 400)

        estimated_tokens = max(1, (len(prompt) + 3) // 4)
        reservation = await self.limiter.reserve(api_key, estimated_tokens)
        if not reservation.admitted:
            raise GatewayError(
                "rate_limited",
                "Token budget exceeded",
                429,
                retry_after=reservation.retry_after,
            )
        assert reservation.row_id is not None

        try:
            result = await self._request_provider(
                self.primary_client, self.primary_url, body
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("Primary provider timed out; attempting fallback")
            return await self._fallback(body, reservation.row_id)
        except httpx.TimeoutException as exc:
            logger.warning("Primary provider timed out: %s", exc)
            return await self._fallback(body, reservation.row_id)
        except httpx.HTTPError as exc:
            logger.error("Primary provider transport failure: %s", exc)
            raise GatewayError(
                "provider_error", "The primary provider failed", 502
            ) from exc

        status, provider_body = result
        if status == 429:
            logger.info("Primary provider rate limited; attempting fallback")
            return await self._fallback(body, reservation.row_id)
        if status >= 400:
            logger.error("Primary provider returned HTTP %s", status)
            raise GatewayError(
                "provider_error", "The primary provider failed", 502
            )

        sanitized = self._sanitize_completion(provider_body)
        actual_tokens = self._actual_token_count(sanitized)
        if actual_tokens is not None:
            await self.limiter.reconcile(reservation.row_id, actual_tokens)
        sanitized["failover"] = False
        return sanitized

    @staticmethod
    def _authenticate(authorization: str | None) -> str:
        if not authorization:
            raise GatewayError("unauthorized", "Invalid API key", 401)
        scheme, separator, key = authorization.partition(" ")
        if scheme != "Bearer" or not separator or not key or " " in key:
            raise GatewayError("unauthorized", "Invalid API key", 401)
        if API_KEYS.get(key) is None:
            raise GatewayError("unauthorized", "Invalid API key", 401)
        return key

    async def _request_provider(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        body: dict[str, Any],
    ) -> tuple[int, Any]:
        response = await asyncio.wait_for(
            client.post(
                base_url + COMPLETION_PATH,
                json=body,
                timeout=self.timeout_seconds,
            ),
            timeout=self.timeout_seconds,
        )

        if response.status_code >= 400:
            return response.status_code, None
        try:
            provider_body = response.json()
        except ValueError as exc:
            logger.error("Provider returned a non-JSON completion")
            raise GatewayError(
                "provider_error", "The provider returned an invalid response", 502
            ) from exc
        return response.status_code, provider_body

    async def _fallback(
        self, body: dict[str, Any], reservation_id: int
    ) -> dict[str, Any]:
        try:
            status, provider_body = await self._request_provider(
                self.secondary_client, self.secondary_url, body
            )
            if status >= 400:
                logger.error("Secondary provider returned HTTP %s", status)
                raise GatewayError(
                    "all_providers_failed",
                    "All providers failed",
                    502,
                )
            sanitized = self._sanitize_completion(provider_body)
            actual_tokens = self._actual_token_count(sanitized)
            if actual_tokens is not None:
                await self.limiter.reconcile(reservation_id, actual_tokens)
            sanitized["failover"] = True
            return sanitized
        except (
            asyncio.TimeoutError,
            TimeoutError,
            httpx.TimeoutException,
            httpx.HTTPError,
        ) as exc:
            logger.error("Secondary provider failed: %s", exc)
            raise GatewayError(
                "all_providers_failed", "All providers failed", 502
            ) from exc
        except GatewayError as exc:
            logger.error("Secondary provider returned an invalid response")
            raise GatewayError(
                "all_providers_failed", "All providers failed", 502
            ) from exc

    @staticmethod
    def _sanitize_completion(provider_body: Any) -> dict[str, Any]:
        if not isinstance(provider_body, dict):
            raise GatewayError(
                "provider_error", "The provider returned an invalid response", 502
            )
        allowed: dict[str, Any] = {}
        for field in ("id", "object", "created", "model"):
            value = provider_body.get(field)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                allowed[field] = value

        choices = provider_body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise GatewayError(
                "provider_error", "The provider returned an invalid response", 502
            )
        sanitized_choices: list[dict[str, Any]] = []
        for choice in choices:
            if not isinstance(choice, dict):
                raise GatewayError(
                    "provider_error", "The provider returned an invalid response", 502
                )
            safe_choice: dict[str, Any] = {}
            for field in ("index", "text", "finish_reason"):
                value = choice.get(field)
                if isinstance(value, (str, int)) and not isinstance(value, bool):
                    safe_choice[field] = value
            if "message" in choice and isinstance(choice["message"], dict):
                message = choice["message"]
                safe_message = {
                    key: message[key]
                    for key in ("role", "content")
                    if isinstance(message.get(key), str)
                }
                safe_choice["message"] = safe_message
            sanitized_choices.append(safe_choice)
        allowed["choices"] = sanitized_choices

        usage = provider_body.get("usage")
        if isinstance(usage, dict):
            safe_usage = {
                field: usage[field]
                for field in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage.get(field), int)
                and not isinstance(usage.get(field), bool)
                and usage[field] >= 0
            }
            if safe_usage:
                allowed["usage"] = safe_usage
        return allowed

    @staticmethod
    def _actual_token_count(body: dict[str, Any]) -> int | None:
        usage = body.get("usage")
        if isinstance(usage, dict):
            total = usage.get("total_tokens")
            if isinstance(total, int) and not isinstance(total, bool):
                return total
        return None
