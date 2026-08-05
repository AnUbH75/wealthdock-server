"""FastAPI application factory for wealthdock-server."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wealthdock_server.api.v1.auth import router as auth_router
from wealthdock_server.api.v1.sync import router as sync_router
from wealthdock_server.core.config import get_settings


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
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness check used by orchestrators/self-host deployments."""
        return {"status": "ok"}

    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(sync_router, prefix="/api/v1/sync", tags=["sync"])

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
