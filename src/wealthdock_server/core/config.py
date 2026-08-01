"""Application settings, read from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for wealthdock-server.

    Values are sourced from environment variables (or a `.env` file in
    local development, see `.env.example` for the full list of keys).
    """

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "info"

    database_url: str = "postgresql+asyncpg://wealthdock:wealthdock@localhost:5432/wealthdock"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    """Return a cached `Settings` instance.

    Cached so repeated calls (e.g. via FastAPI dependency injection) don't
    re-parse the environment on every request.
    """
    return Settings()
