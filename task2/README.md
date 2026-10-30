# Task 2: MCP Security Gateway

A FastAPI JSON-RPC reverse proxy at `POST /mcp`. It authenticates bearer
tokens, forwards allowed calls to a downstream MCP endpoint, and blocks
`admin_` tools for viewer credentials before they reach the downstream server.
The bundled downstream mock advertises a viewer tool and an admin tool.

## Requirements

- Python 3.10+

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

Start the mock and gateway in separate terminals:

```bash
uvicorn downstream_server:app --port 8001
uvicorn gateway:app --port 8000
```

The gateway expects `Authorization: Bearer viewer-token` or
`Authorization: Bearer admin-token`. Set `MCP_DOWNSTREAM_URL` to override the
downstream URL.

## Tests

```bash
pytest -q
```
