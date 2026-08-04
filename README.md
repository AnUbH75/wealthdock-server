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

## Key Management & Encryption

Sensitive financial data (account numbers, balances, bank credentials/tokens) is encrypted at rest at the application layer using AES-256 (via cryptography's Fernet implementation).

For self-hosted and production deployments:
1. Set the `ENCRYPTION_KEY` environment variable (or configure it in your `.env` file).
2. The key must be a 32-byte, URL-safe, base64-encoded string.
3. You can generate a new secure key by running:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
4. **Important**: Store this key securely. If this key is lost or modified, all previously encrypted data in the database will be unrecoverable.

## License

MIT — see [LICENSE](LICENSE).

