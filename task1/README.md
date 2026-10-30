# Task 1: Strict MCP Server

A runnable MCP server built with the official Python SDK's low-level `Server`.
It exposes `get_customer_record` and `trigger_refund` over stdio, validates
arguments with strict Pydantic v2 models, and reports invalid parameters as
JSON-RPC errors (`-32602`). Customer records are held in a small in-memory
database; an unknown customer is returned as a normal tool result with
`isError: true`.

## Requirements

- Python 3.10+

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
python server.py
```

The server communicates only over stdin/stdout using MCP stdio transport.
Logging is sent to stderr.

## Tools

- `get_customer_record(customer_id)`: `customer_id` must match `CUST-` followed
  by exactly five alphanumeric characters.
- `trigger_refund(customer_id, amount, reason)`: uses the same ID format,
  requires a positive numeric amount, and a reason containing at least ten
  non-whitespace characters.

Both tools reject extra arguments. Validly shaped requests for unknown
customers return a business-level not-found tool result rather than a protocol
error.

## Tests

```bash
pytest -q
```
