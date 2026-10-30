# Task 4: Rate-Limited Model Router

A FastAPI completion gateway with bearer-key tenant authentication, an
on-disk SQLite sliding-window token ledger, and controlled primary-to-secondary
provider fallback. Upstream errors are logged locally and converted into
sanitized client errors.

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
uvicorn providers:primary_app --port 8001
uvicorn providers:secondary_app --port 8002
uvicorn gateway:app --port 8000
```

The default tenant keys are `tenant-alpha-key` and `tenant-beta-key`.
`GATEWAY_DB_PATH`, `PRIMARY_PROVIDER_URL`, and `SECONDARY_PROVIDER_URL` may be
set to override the local defaults.

## Tests

```bash
pytest -q
```
