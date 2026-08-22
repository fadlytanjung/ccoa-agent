"""Typed settings, validated once at import.

A missing or contradictory value fails the process at boot rather than producing a
``500`` on the first real request — see docs/06 §3.8 and docs/03 §3.6.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "prod"]
AuthMode = Literal["cognito", "dev"]

#: Mitigation for CVE-2026-28277 (msgpack deserialisation → RCE). Set before anything
#: imports a checkpointer, because the library reads it at import time.
STRICT_MSGPACK_VAR = "LANGGRAPH_STRICT_MSGPACK"


class Settings(BaseSettings):
    """Everything the process needs to know, resolved from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    environment: Environment = "local"
    log_level: str = "INFO"
    build_sha: str = "unknown"

    # --- Model ------------------------------------------------------------
    gemini_api_key: SecretStr = SecretStr("")
    #: Cheapest stable model with tool calling strong enough for the investigation
    #: loop. Preview IDs are avoided deliberately — docs/02 §3.1.
    gemini_model: str = "gemini-3.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_timeout_seconds: int = 30

    # --- Tracing ----------------------------------------------------------
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr = SecretStr("")
    langsmith_project: str = "ccoa-local"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # --- Data -------------------------------------------------------------
    db_path: Path = Path("./data/app.db")
    checkpoint_db_path: Path = Path("./data/checkpoints.db")

    # --- Identity ---------------------------------------------------------
    auth_mode: AuthMode = "cognito"
    cognito_user_pool_id: str = "local-dev"
    cognito_client_id: str = "local-dev"
    cognito_region: str = "ap-southeast-1"
    #: Hosted-UI domain. Accepts the prefix the console shows on "Domain name"
    #: (``ccoa-dev``), a full host, or a full URL — the SPA normalises all three
    #: (docs/18 §7). Empty locally, where AUTH_MODE=dev bypasses the flow entirely.
    cognito_domain: str = ""
    jwks_cache_seconds: int = 3600

    # --- Features ---------------------------------------------------------
    enable_vector_search: bool = False
    cors_origins: list[str] = Field(default_factory=list)

    # --- Graph bounds (docs/05 §3.5) --------------------------------------
    max_investigation_iterations: int = 6
    max_parallel_tools: int = 3
    max_distinct_tools: int = 5
    investigation_wall_clock_seconds: int = 45
    min_intent_confidence: float = 0.6

    @property
    def cognito_issuer(self) -> str:
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"
        )

    @property
    def jwks_url(self) -> str:
        return f"{self.cognito_issuer}/.well-known/jwks.json"

    @property
    def is_deployed(self) -> bool:
        return self.environment in ("dev", "prod")

    @model_validator(mode="after")
    def _dev_auth_never_ships(self) -> Settings:
        """``AUTH_MODE=dev`` is only legal locally — docs/14 §3.7.

        A deployed task configured this way must fail to boot rather than serve
        unauthenticated traffic. This is the guard the spec promises, and
        ``tests/unit/test_config.py`` asserts it so removing it fails the build.
        """
        if self.auth_mode == "dev" and self.environment != "local":
            raise ValueError(
                f"auth_mode='dev' is only permitted when environment='local' "
                f"(got environment={self.environment!r}). Refusing to start."
            )
        return self

    @model_validator(mode="after")
    def _model_key_required_when_deployed(self) -> Settings:
        """Locally the key is optional so tests, lint, and types run without one."""
        if self.is_deployed and not self.gemini_api_key.get_secret_value():
            raise ValueError("gemini_api_key is required when environment is dev or prod")
        return self

    @model_validator(mode="after")
    def _tracing_needs_a_key(self) -> Settings:
        """Tracing on with no key would silently trace nothing, which is worse than
        being off — the operator would believe they had observability."""
        if self.langsmith_tracing and not self.langsmith_api_key.get_secret_value():
            raise ValueError("langsmith_tracing is enabled but langsmith_api_key is empty")
        return self


def apply_langsmith_env(settings: Settings) -> None:
    """Export LangSmith configuration for the tracing SDK.

    LangChain reads these from the environment rather than from a client object, so the
    only way to configure it is to set them. Doing it here — once, from validated
    settings — keeps the opt-in switch in one place (docs/10 §6).
    """
    if not settings.langsmith_tracing:
        # Explicitly off rather than absent: an inherited LANGSMITH_TRACING=true from
        # the shell must not silently re-enable third-party data egress.
        os.environ["LANGSMITH_TRACING"] = "false"
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project


def enforce_strict_msgpack(environment: Environment) -> None:
    """Guarantee the CVE-2026-28277 mitigation is active.

    Unset defaults to ``true`` with a warning; an explicit opt-out is refused outside
    local development. docs/02 §4.2 makes this mandatory, not advisory.
    """
    raw = os.environ.get(STRICT_MSGPACK_VAR)
    if raw is None:
        os.environ[STRICT_MSGPACK_VAR] = "true"
        return
    disabled = raw.strip().lower() not in ("1", "true", "yes", "on")
    if disabled and environment != "local":
        raise RuntimeError(
            f"{STRICT_MSGPACK_VAR}={raw!r} disables the CVE-2026-28277 mitigation. "
            f"Refusing to start in environment={environment!r}."
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings singleton.

    Not ``lru_cache``d so tests can reset it explicitly via :func:`reset_settings`.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
        enforce_strict_msgpack(_settings.environment)
    return _settings


def reset_settings() -> None:
    """Drop the cached settings. Test-only."""
    global _settings
    _settings = None
