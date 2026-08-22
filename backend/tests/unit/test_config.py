"""Configuration guards — docs/14 §3.7, docs/02 §4.2.

Two of these assertions exist so that removing the guard fails the build. They are the
only thing standing between a misconfigured deploy and a task that serves
unauthenticated traffic or runs with a known RCE mitigation disabled.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import STRICT_MSGPACK_VAR, Settings, enforce_strict_msgpack


class TestDevAuthGuard:
    def test_dev_auth_is_allowed_locally(self) -> None:
        settings = Settings(environment="local", auth_mode="dev")
        assert settings.auth_mode == "dev"

    @pytest.mark.parametrize("environment", ["dev", "prod"])
    def test_dev_auth_cannot_ship(self, environment: str) -> None:
        with pytest.raises(ValidationError, match="only permitted when environment='local'"):
            Settings(
                environment=environment,  # type: ignore[arg-type]
                auth_mode="dev",
                gemini_api_key="k",  # type: ignore[arg-type]
            )

    def test_deployed_environments_require_a_model_key(self) -> None:
        with pytest.raises(ValidationError, match="gemini_api_key is required"):
            Settings(environment="dev", auth_mode="cognito", gemini_api_key="")  # type: ignore[arg-type]


class TestTracingGuard:
    def test_tracing_without_a_key_fails_loudly(self) -> None:
        # Tracing enabled with no key would trace nothing while looking enabled, which
        # is worse than being off.
        with pytest.raises(ValidationError, match="langsmith_api_key is empty"):
            Settings(environment="local", langsmith_tracing=True, langsmith_api_key="")  # type: ignore[arg-type]

    def test_tracing_with_a_key_is_accepted(self) -> None:
        settings = Settings(
            environment="local",
            langsmith_tracing=True,
            langsmith_api_key="ls-key",  # type: ignore[arg-type]
        )
        assert settings.langsmith_tracing is True


class TestStrictMsgpack:
    def test_unset_defaults_to_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(STRICT_MSGPACK_VAR, raising=False)
        enforce_strict_msgpack("local")
        import os

        assert os.environ[STRICT_MSGPACK_VAR] == "true"

    def test_explicit_opt_out_is_refused_when_deployed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(STRICT_MSGPACK_VAR, "false")
        with pytest.raises(RuntimeError, match="CVE-2026-28277"):
            enforce_strict_msgpack("dev")

    def test_explicit_opt_out_is_tolerated_locally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Deliberate: a developer debugging deserialisation locally is not a production
        # risk, and the guard exists to stop it shipping, not to stop it existing.
        monkeypatch.setenv(STRICT_MSGPACK_VAR, "false")
        enforce_strict_msgpack("local")


def test_secrets_are_not_stringified(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(environment="local", gemini_api_key="super-secret")  # type: ignore[arg-type]
    assert "super-secret" not in str(settings)
    assert "super-secret" not in repr(settings)
    assert settings.gemini_api_key.get_secret_value() == "super-secret"
