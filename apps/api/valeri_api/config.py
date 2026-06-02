"""Application settings, read from the environment. No secrets in code."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the VALERI API."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://valeri:valeri@localhost:5432/valeri"
    app_env: str = "development"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (cache is cleared in tests)."""
    return Settings()
