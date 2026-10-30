"""Low-level MCP server implementation."""

import logging
from typing import Any

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import (
    CallToolResult,
    CallToolRequest,
    ErrorData,
    ServerResult,
    TextContent,
    Tool,
)
from pydantic import ValidationError

from config import INVALID_PARAMS_CODE, SERVER_NAME, SERVER_VERSION
from strict_mcp_server.models import CustomerRecordArguments, RefundArguments

logger = logging.getLogger(SERVER_NAME)

CUSTOMERS: dict[str, dict[str, str]] = {
    "CUST-A1234": {"name": "Ada Lovelace", "email": "ada@example.com"},
    "CUST-B5678": {"name": "Grace Hopper", "email": "grace@example.com"},
}

server = Server(SERVER_NAME)


def _invalid_params(message: str) -> McpError:
    return McpError(
        ErrorData(code=INVALID_PARAMS_CODE, message=message)
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise tools and their input schemas to MCP clients."""
    return [
        Tool(
            name="get_customer_record",
            description="Retrieve a customer record by customer ID.",
            inputSchema=CustomerRecordArguments.model_json_schema(),
        ),
        Tool(
            name="trigger_refund",
            description="Record a refund request for a customer.",
            inputSchema=RefundArguments.model_json_schema(),
        ),
    ]


async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[TextContent] | CallToolResult:
    """Validate and execute a requested tool."""
    models = {
        "get_customer_record": CustomerRecordArguments,
        "trigger_refund": RefundArguments,
    }
    model = models.get(name)
    if model is None:
        raise _invalid_params(f"Unknown tool: {name}")

    try:
        validated = model.model_validate(arguments)
    except ValidationError as exc:
        raise _invalid_params(str(exc)) from exc

    customer = CUSTOMERS.get(validated.customer_id)
    if customer is None:
        logger.info("Customer lookup returned not found")
        return CallToolResult(
            content=[TextContent(type="text", text="Customer not found")],
            isError=True,
        )

    if name == "get_customer_record":
        logger.info("Customer record retrieved")
        return [
            TextContent(
                type="text",
                text=(
                    f"Customer {validated.customer_id}: "
                    f"{customer['name']} ({customer['email']})"
                ),
            )
        ]

    refund = validated
    assert isinstance(refund, RefundArguments)
    logger.info("Refund request accepted")
    return [
        TextContent(
            type="text",
            text=(
                f"Refund request accepted for {refund.customer_id}: "
                f"{refund.amount:.2f}"
            ),
        )
    ]


async def _handle_call_tool_request(request: CallToolRequest) -> ServerResult:
    result = await call_tool(request.params.name, request.params.arguments or {})
    if isinstance(result, CallToolResult):
        return ServerResult(result)
    return ServerResult(CallToolResult(content=result, isError=False))


server.request_handlers[CallToolRequest] = _handle_call_tool_request


async def run() -> None:
    """Serve MCP over stdio, keeping protocol output on stdout."""
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler()],
        force=True,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
