"""Application settings, read from the environment. No secrets in code."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the VALERI API."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://valeri:valeri@localhost:5432/valeri"
    app_env: str = "development"

    # ── LLM gateway (M6) — hosted Claude via LiteLLM, OpenAI-compatible ──────
    litellm_base_url: str = "http://litellm:4000"
    litellm_master_key: str = ""  # secret, from env
    llm_tier1_model: str = "tier1"  # LiteLLM model name → Claude Haiku 4.5
    llm_narration_enabled: bool = True
    llm_max_retries: int = 2

    # ── PII masking (M6) — pseudonym salt; load-bearing, keep secret ─────────
    pii_salt: str = "dev-only-salt-change-me"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (cache is cleared in tests)."""
    return Settings()
