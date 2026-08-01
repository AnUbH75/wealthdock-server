# Contributing to wealthdock-server

Thanks for your interest in contributing.

## Setup

```bash
uv sync --all-extras
pre-commit install
cp .env.example .env
docker compose up -d
uv run alembic upgrade head
```

## Before opening a PR

- `uv run ruff check . && uv run ruff format --check .`
- `uv run mypy src tests`
- `uv run pytest`

## Migrations

Add a new Alembic revision after changing SQLAlchemy models:

```bash
uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated migration before committing it.

## Pull requests

Keep PRs focused on a single change. Fill out the PR template and link any related issue.
