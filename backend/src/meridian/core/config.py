from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent

LLMTier = Literal["planner", "worker", "critic", "writer"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    api_key: SecretStr | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit_per_minute: int = 30

    database_url: str = "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian"
    redis_url: str | None = "redis://localhost:6379/0"

    # LLM: "auto" uses Anthropic when a key is present, otherwise the deterministic offline mode.
    llm_provider: Literal["auto", "anthropic", "offline"] = "auto"
    anthropic_api_key: SecretStr | None = None
    model_planner: str = "claude-sonnet-5"
    model_worker: str = "claude-haiku-4-5-20251001"
    model_critic: str = "claude-sonnet-5"
    model_writer: str = "claude-sonnet-5"
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 3

    # Data: "live" = network only, "snapshot" = recorded fixtures only, "auto" = live with snapshot fallback.
    data_mode: Literal["live", "snapshot", "auto"] = "auto"
    snapshot_dir: Path = BACKEND_ROOT / "snapshots"
    sec_user_agent: str = "Meridian Research Platform contact@example.com"
    http_timeout_seconds: float = 20.0

    fmp_api_key: SecretStr | None = None
    alpha_vantage_api_key: SecretStr | None = None
    finnhub_api_key: SecretStr | None = None
    polygon_api_key: SecretStr | None = None
    fred_api_key: SecretStr | None = None

    embedding_provider: Literal["fastembed", "hashing"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    model_cache_dir: Path = BACKEND_ROOT / ".models"

    require_approval_default: bool = True
    max_revision_rounds: int = 2
    max_supervisor_loops: int = 2
    agent_timeout_seconds: float = 180.0
    graph_recursion_limit: int = 60

    otel_exporter_otlp_endpoint: str | None = None
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "meridian"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def llm_mode(self) -> Literal["anthropic", "offline"]:
        if self.llm_provider == "auto":
            return "anthropic" if self.anthropic_api_key else "offline"
        return self.llm_provider

    def model_for(self, tier: LLMTier) -> str:
        return {
            "planner": self.model_planner,
            "worker": self.model_worker,
            "critic": self.model_critic,
            "writer": self.model_writer,
        }[tier]


@lru_cache
def get_settings() -> Settings:
    return Settings()
