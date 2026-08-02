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

## Self-Hosting & Deployment

`wealthdock-server` can be deployed as self-hosted infrastructure using Docker and Docker Compose.

### Quick Start with Docker Compose

1. Build and bring up the containerized application and database services:
   ```bash
   docker compose up -d
   ```
2. The setup automatically applies database migrations (`alembic upgrade head`) and starts the server at `http://localhost:8000`.

### Configuration

All settings are configured via environment variables. Create a `.env` file in the root directory (or inject variables directly in your environment):

- `DATABASE_URL`: Connection string for PostgreSQL (e.g. `postgresql+asyncpg://user:pass@host:port/db`).
- `APP_ENV`: Application environment (`production` or `development`).
- `JWT_SECRET`: Secret key used to sign JWT authentication tokens (ensure this is a secure, random string in production).
- `JWT_ALGORITHM`: Signature algorithm (defaults to `HS256`).
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: Expiry duration for authentication tokens (defaults to `60`).

## License

MIT — see [LICENSE](LICENSE).

