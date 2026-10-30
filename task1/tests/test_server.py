"""Validation, protocol, and stdio integration tests."""

import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from config import INVALID_PARAMS_CODE
from strict_mcp_server.models import CustomerRecordArguments, RefundArguments
from strict_mcp_server.server import call_tool

TASK_DIR = Path(__file__).resolve().parents[1]
VALID_CUSTOMER_ID = "CUST-A1234"


def test_pydantic_happy_paths() -> None:
    customer = CustomerRecordArguments.model_validate(
        {"customer_id": VALID_CUSTOMER_ID}
    )
    refund = RefundArguments.model_validate(
        {
            "customer_id": VALID_CUSTOMER_ID,
            "amount": 12.5,
            "reason": "Customer returned item",
        }
    )

    assert customer.customer_id == VALID_CUSTOMER_ID
    assert refund.amount == 12.5


@pytest.mark.parametrize(
    "payload",
    [
        {"customer_id": "CUST-1234"},
        {"customer_id": "CUST-123456"},
        {"customer_id": "CUST-12-34"},
        {"customer_id": "cust-A1234"},
        {"customer_id": "CUST-A1234\n"},
        {"customer_id": "CUST-Ａ1234"},
        {"customer_id": "CUST-A1234", "extra": True},
    ],
)
def test_customer_arguments_reject_invalid_id_and_extra_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CustomerRecordArguments.model_validate(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"customer_id": "CUST-1234"},
        {"amount": 0.0},
        {"amount": -1.0},
        {"amount": "12.5"},
        {"reason": "too short"},
        {"reason": "          "},
        {"reason": "123456789 "},
        {"extra": True},
    ],
)
def test_refund_arguments_reject_invalid_values(
    changes: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "customer_id": VALID_CUSTOMER_ID,
        "amount": 12.5,
        "reason": "Customer returned item",
    }
    payload.update(changes)
    with pytest.raises(ValidationError):
        RefundArguments.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_customer_record", {"customer_id": "invalid"}),
        (
            "trigger_refund",
            {
                "customer_id": VALID_CUSTOMER_ID,
                "amount": -2.0,
                "reason": "Customer returned item",
            },
        ),
        ("not_a_tool", {}),
    ],
)
async def test_invalid_requests_raise_invalid_params(
    name: str, arguments: dict[str, object]
) -> None:
    with pytest.raises(McpError) as error:
        await call_tool(name, arguments)
    assert error.value.error.code == INVALID_PARAMS_CODE


async def _connect(log_file=None):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(TASK_DIR / "server.py")],
    )
    client_context = (
        stdio_client(parameters, errlog=log_file)
        if log_file is not None
        else stdio_client(parameters)
    )
    return client_context


@pytest.mark.asyncio
async def test_real_stdio_protocol_and_business_not_found() -> None:
    async with await _connect() as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "get_customer_record",
                "trigger_refund",
            }

            customer_result = await session.call_tool(
                "get_customer_record", {"customer_id": VALID_CUSTOMER_ID}
            )
            assert customer_result.isError is False
            assert "Ada Lovelace" in customer_result.content[0].text

            refund_result = await session.call_tool(
                "trigger_refund",
                {
                    "customer_id": VALID_CUSTOMER_ID,
                    "amount": 25.0,
                    "reason": "Refund for returned product",
                },
            )
            assert refund_result.isError is False

            with pytest.raises(McpError) as invalid:
                await session.call_tool(
                    "get_customer_record", {"customer_id": "not-valid"}
                )
            assert invalid.value.error.code == INVALID_PARAMS_CODE

            with pytest.raises(McpError) as unknown:
                await session.call_tool("missing_tool", {})
            assert unknown.value.error.code == INVALID_PARAMS_CODE

            not_found = await session.call_tool(
                "get_customer_record", {"customer_id": "CUST-Z9999"}
            )
            assert not_found.isError is True
            assert not_found.content[0].text == "Customer not found"


@pytest.mark.asyncio
async def test_stdio_keeps_protocol_on_stdout_and_logs_on_stderr(
    tmp_path: Path,
) -> None:
    stderr_path = tmp_path / "server.stderr"
    with stderr_path.open("w+", encoding="utf-8") as stderr_file:
        async with await _connect(stderr_file) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "strict-mcp-server"
                await session.call_tool(
                    "get_customer_record", {"customer_id": VALID_CUSTOMER_ID}
                )

        stderr_file.flush()

    stderr_text = stderr_path.read_text(encoding="utf-8")
    assert "Customer record retrieved" in stderr_text
    assert "jsonrpc" not in stderr_text.lower()
