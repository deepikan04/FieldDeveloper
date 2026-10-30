"""In-process gateway and downstream integration tests."""

import json
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from mcp_security_gateway.downstream import create_downstream_app
from mcp_security_gateway.gateway import create_app


@pytest.fixture
def downstream():
    from mcp_security_gateway import downstream

    downstream.admin_reset_key_invocations = 0
    return create_downstream_app()


@pytest.fixture
async def gateway_client(downstream):
    transport = httpx.ASGITransport(app=downstream)
    app = create_app(transport=transport)
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            yield client


async def send(
    client: httpx.AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    token: str = "viewer-token",
) -> httpx.Response:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return await client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        content=json.dumps(body),
    )


@pytest.mark.asyncio
async def test_tools_list_forwards_for_any_authenticated_role(gateway_client):
    for token in ("viewer-token", "admin-token"):
        response = await send(gateway_client, "tools/list", token=token)
        assert response.status_code == 200
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
            "get_time",
            "admin_reset_key",
        }


@pytest.mark.asyncio
async def test_viewer_tool_call_is_forwarded(gateway_client):
    response = await send(
        gateway_client, "tools/call", {"name": "get_time", "arguments": {}}
    )
    assert response.status_code == 200
    assert "T" in response.json()["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_viewer_admin_call_is_blocked_before_downstream(gateway_client):
    from mcp_security_gateway import downstream

    response = await send(
        gateway_client,
        "tools/call",
        {"name": "admin_reset_key", "arguments": {}},
    )
    assert response.json()["error"]["code"] == -32001
    assert response.json()["error"]["message"] == "Unauthorized Tool Call"
    assert downstream.admin_reset_key_invocations == 0


@pytest.mark.asyncio
async def test_admin_call_executes_downstream(gateway_client):
    from mcp_security_gateway import downstream

    response = await send(
        gateway_client,
        "tools/call",
        {"name": "admin_reset_key", "arguments": {}},
        token="admin-token",
    )
    assert response.status_code == 200
    assert response.json()["result"]["content"][0]["text"] == "Key reset"
    assert downstream.admin_reset_key_invocations == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    [None, "Basic viewer-token", "Bearer unknown-token"],
)
async def test_authentication_failures_are_local(gateway_client, authorization):
    headers = {} if authorization is None else {"Authorization": authorization}
    response = await gateway_client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.json()["error"]["code"] == -32001


@pytest.mark.asyncio
async def test_rpc_parse_and_parameter_errors(gateway_client):
    headers = {"Authorization": "Bearer viewer-token"}
    malformed = await gateway_client.post(
        "/mcp", headers=headers, content='{"jsonrpc":'
    )
    assert malformed.json()["error"]["code"] == -32700

    invalid_request = await gateway_client.post(
        "/mcp", headers=headers, json={"method": "tools/list"}
    )
    assert invalid_request.json()["error"]["code"] == -32600

    missing_params = await send(gateway_client, "tools/call")
    assert missing_params.json()["error"]["code"] == -32602
