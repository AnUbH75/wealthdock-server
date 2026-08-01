"""FastAPI application factory for wealthdock-server."""

from fastapi import FastAPI


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

    return app


app = create_app()
