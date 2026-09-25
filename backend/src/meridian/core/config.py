from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    # NoDecode: pydantic-settings JSON-decodes complex types in the env source before validators run, so a
    # plain "http://a,http://b" in .env would raise before _split_origins could parse it.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit_per_minute: int = 30

    database_url: str = "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian"
    redis_url: str | None = "redis://localhost:6379/0"

    # LLM: "auto" uses Anthropic when a key is present, otherwise the deterministic offline mode.
    llm_provider: Literal["auto", "anthropic", "offline"] = "auto"
    anthropic_api_key: SecretStr | None = None
    model_planner: str = "claude-opus-5"
    model_worker: str = "claude-sonnet-5"
    model_critic: str = "claude-opus-5"
    model_writer: str = "claude-opus-5"
    effort_planner: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    effort_worker: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    effort_critic: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    effort_writer: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_refusal_fallbacks: bool = True  # server-side refusal fallbacks on Opus 5
    llm_timeout_seconds: float = 300.0
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
    agent_timeout_seconds: float = 300.0
    graph_recursion_limit: int = 60

    otel_exporter_otlp_endpoint: str | None = None
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "meridian"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept both "http://a,http://b" and a JSON array, so .env stays human-writable."""
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [o.strip() for o in text.split(",") if o.strip()]
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

    def effort_for(self, tier: LLMTier) -> str:
        return {
            "planner": self.effort_planner,
            "worker": self.effort_worker,
            "critic": self.effort_critic,
            "writer": self.effort_writer,
        }[tier]


@lru_cache
def get_settings() -> Settings:
    return Settings()
