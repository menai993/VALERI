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
    # LiteLLM aliases per tier (M12). The app addresses the gateway by ALIAS only;
    # the alias→Claude-model mapping lives in infra/litellm.config.yaml + .env
    # (LLM_TIER*_MODEL), so swapping a tier's model never touches code.
    llm_tier1_alias: str = "tier1"  # → Claude Haiku 4.5
    llm_tier2_alias: str = "tier2"  # → Claude Sonnet 4.6
    llm_tier2_strong_alias: str = "tier2_strong"  # → Claude Opus 4.8
    llm_narration_enabled: bool = True
    llm_max_retries: int = 2
    # Prompt caching (M12 cost lever): stable system prompts are marked cacheable.
    llm_prompt_cache_enabled: bool = True

    # ── PII masking (M6) — pseudonym salt; load-bearing, keep secret ─────────
    pii_salt: str = "dev-only-salt-change-me"

    # ── Auth (M8) — JWT in an httpOnly cookie; secret from env in production ──
    auth_secret: str = "dev-only-auth-secret-change-me-immediately"  # >= 32 bytes for HS256
    auth_token_hours: int = 12

    # ── DI1a — document object storage (MinIO, S3-compatible) ────────────────
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = "valeri"
    minio_secret_key: str = "valeri-minio-2026"  # secret, from env
    minio_bucket: str = "valeri-documents"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (cache is cleared in tests)."""
    return Settings()
