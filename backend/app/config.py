from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from env vars prefixed WENSDAY_ (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="WENSDAY_", env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    database_url: str = "sqlite+aiosqlite:///./wensday.db"
    redis_url: str | None = None
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None

    # auth
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    token_encryption_key: str | None = None  # Fernet key for OAuth tokens at rest
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    web_origin: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # LLM: ordered failover chain; "offline" (rule-based) is always the last resort
    llm_chain: list[str] = Field(default_factory=lambda: ["anthropic", "openai_compat", "offline"])
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"  # also Ollama/vLLM: http://localhost:11434/v1
    openai_model: str = "gpt-4o-mini"
    embedding_provider: str = "hashing"  # hashing (offline) | openai_compat
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 256

    # voice
    stt_provider: str = "browser"  # browser | whisper | azure
    tts_provider: str = "browser"  # browser | azure
    azure_speech_key: str | None = None
    azure_speech_region: str | None = None
    whisper_base_url: str | None = None
    voice_ta: str = "ta-IN-PallaviNeural"
    voice_en: str = "en-IN-NeerjaNeural"

    default_timezone: str = "Asia/Kolkata"
    reminder_worker: bool = True
    plugin_dir: str | None = None
    auto_create_tables: bool = True  # dev/test convenience; in prod run migrations instead
    rate_limit_per_minute: int = 120
    ws_connect_limit_per_minute: int = 30  # per-IP; a websocket connection is heavier than a REST call


@lru_cache
def get_settings() -> Settings:
    return Settings()
