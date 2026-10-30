# Task 3: Streaming PII Redaction Gateway

A FastAPI LLM gateway that parses OpenAI-style SSE deltas, redacts emails,
US SSNs, and payment-card numbers in flight, and re-emits redacted SSE content.
The redactor retains only a bounded raw suffix so matches split across provider
chunks are not leaked.

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
uvicorn provider:app --port 8001
uvicorn gateway:app --port 8000
```

Send `POST /v1/stream` with `{"text":"..."}` or `{"inject":"pii"}`. Set
`LLM_PROVIDER_URL` to override the provider URL.

## Tests

```bash
pytest -q
```
