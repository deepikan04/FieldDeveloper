# FieldDeveloper

Four standalone Python 3.10+ take-home tasks. Each task has its own
`pyproject.toml`, source package, README, test suite, and virtual environment.

| Task | Project | Main feature | Quick start |
|---|---|---|---|
| 1 | [Custom MCP Server](./task1/README.md) | Low-level MCP stdio server with strict Pydantic validation | `cd task1 && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q` |
| 2 | [MCP Security Gateway](./task2/README.md) | Authenticated JSON-RPC proxy with role-based tool filtering | `cd task2 && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q` |
| 3 | [Streaming PII Gateway](./task3/README.md) | SSE LLM proxy with bounded in-flight PII redaction | `cd task3 && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q` |
| 4 | [Rate-Limited Model Router](./task4/README.md) | SQLite token-window limiting and controlled provider fallback | `cd task4 && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q` |

Use Python 3.10 or later for each environment. To run a task's application and
its mock provider/downstream service, follow that task's README.
