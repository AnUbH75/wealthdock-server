"""FastAPI application factory for wealthdock-server."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wealthdock_server.core.config import get_settings
from wealthdock_server.db.session import engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle event handlers."""
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Domain routers get mounted under `/api/v1` as they're added. A
    top-level `/health` endpoint is exposed for liveness checks.
    """
    app = FastAPI(
        title="wealthdock-server",
        description=(
            "Self-hostable backend for wealthdock: cross-device sync, bank-API "
            "integration, data storage, auth, and encryption of sensitive "
            "financial data."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness check used by orchestrators/self-host deployments."""
        return {"status": "ok"}

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


app = create_app()
