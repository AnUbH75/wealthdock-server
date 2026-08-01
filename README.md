# wealthdock-server

Self-hostable backend for [wealthdock](https://github.com/wealthdock/wealthdock) — cross-device sync, bank-API integration, data storage, auth, and encryption of sensitive financial data. Useful entirely on its own as pure backend infrastructure, independent of the UI.

Part of the [wealthdock](https://github.com/wealthdock) organization — see the [org profile](https://github.com/wealthdock/.github) for how the repos fit together.

## Development Setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Docker (for local Postgres).

```bash
uv sync --all-extras
cp .env.example .env
docker compose up -d
uv run alembic upgrade head
```

Run the dev server:

```bash
uv run uvicorn wealthdock_server.main:app --reload
```

Check it's alive:

```bash
curl http://localhost:8000/health
```

Run linting and type checking:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

Run the test suite:

```bash
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
