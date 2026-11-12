"""Environment configuration, loaded once and kept explicit.

Everything is read from environment variables so the same code works for
the CLI, the MCP server (which is spawned as a child process) and tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    # Optional: makes `cp .env.example .env` work without manual exports.
    # The core tool layer still works with plain environment variables when
    # python-dotenv is not installed.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - depends on the installed extras
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    url: str
    api_key: str
    secret_key: str
    verify_tls: bool
    timeout: float
    mock: bool
    allow_write: bool

    @property
    def has_credentials(self) -> bool:
        return bool(self.url and self.api_key and self.secret_key)


def load_settings() -> Settings:
    """Read settings from the environment.

    Mock mode is the default whenever credentials are incomplete, so the
    project is immediately runnable/demoable without a CloudStack cluster.
    Setting CLOUDSTACK_MOCK=false forces real mode and then requires the
    three connection variables.
    """
    url = os.environ.get("CLOUDSTACK_URL", "").strip().rstrip("/")
    api_key = os.environ.get("CLOUDSTACK_API_KEY", "").strip()
    secret_key = os.environ.get("CLOUDSTACK_SECRET_KEY", "").strip()
    has_credentials = bool(url and api_key and secret_key)
    mock = _env_bool("CLOUDSTACK_MOCK", default=not has_credentials)

    if not mock and not has_credentials:
        raise ValueError(
            "CLOUDSTACK_MOCK=false requires CLOUDSTACK_URL, CLOUDSTACK_API_KEY "
            "and CLOUDSTACK_SECRET_KEY"
        )

    return Settings(
        url=url,
        api_key=api_key,
        secret_key=secret_key,
        verify_tls=_env_bool("CLOUDSTACK_VERIFY_TLS", default=True),
        timeout=float(os.environ.get("CLOUDSTACK_TIMEOUT", "30")),
        mock=mock,
        # Read-only by default. Even when enabled, destructive tool calls
        # still require an explicit confirm=true argument.
        allow_write=_env_bool("CLOUDSTACK_AGENT_ALLOW_WRITE", default=False),
    )
