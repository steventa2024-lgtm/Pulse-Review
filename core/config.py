"""Persistent configuration (config.json) with secret *references* instead of plaintext secrets."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import paths
from .security import SecretStore, default_secret_store, load_dotenv

log = logging.getLogger(__name__)

GITHUB_SECRET_REF = "github_token"
GITHUB_REFRESH_REF = "github_refresh_token"
# Optionally bake in the client ID of your own GitHub OAuth App (device flow enabled). Not a secret.
DEFAULT_GITHUB_CLIENT_ID = ""
OPENROUTER_SECRET_REF = "openrouter_api_key"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OPENROUTER_DEFAULT_MODEL = "qwen/qwen3-coder:free"
OPENROUTER_CANDIDATES = [
    "qwen/qwen3-coder:free",
    "deepseek/deepseek-chat-v3.1:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]
OLLAMA_DEFAULT_MODEL = "qwen3-coder:30b"


class GitHubSettings(BaseModel):
    token_ref: str = GITHUB_SECRET_REF
    api_base_url: str = "https://api.github.com"
    web_base_url: str = "https://github.com"
    # OAuth (device flow). The client ID of a GitHub OAuth App / GitHub App is public, not a secret.
    oauth_client_id: str = ""
    auth_method: Literal["", "oauth", "pat"] = ""
    oauth_scopes: str = ""
    include_private_repos: bool = True
    token_expires_at: float | None = None  # epoch seconds; only for expiring (GitHub App) tokens


class OpenRouterSettings(BaseModel):
    api_key_ref: str = OPENROUTER_SECRET_REF
    base_url: str = OPENROUTER_BASE_URL
    model: str = OPENROUTER_DEFAULT_MODEL
    timeout: float = 120.0
    private_repo_consent: bool = False  # persistent opt-in to sending private code to OpenRouter


class OllamaSettings(BaseModel):
    base_url: str = OLLAMA_BASE_URL
    model: str = OLLAMA_DEFAULT_MODEL
    context_length: int = 16384
    timeout: float = 600.0


class ReviewSettings(BaseModel):
    depth: Literal["quick", "standard", "deep"] = "standard"
    max_context_budget: int = 24000  # tokens; upper bound on prompt size (also capped by model metadata)
    max_findings: int = 3
    generate_tests: bool = True
    security_analysis: bool = True
    performance_analysis: bool = True
    run_sandbox_tests: bool = False


class AppSettings(BaseModel):
    watch_poll_minutes: int = 0  # 0 = manual refresh only
    auto_analyze_watched: bool = False  # analysis only; publishing is always manual
    download_dir: str = ""
    theme: Literal["dark"] = "dark"


class AppConfig(BaseModel):
    version: int = 1
    provider: Literal["openrouter", "ollama"] = "openrouter"
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    openrouter: OpenRouterSettings = Field(default_factory=OpenRouterSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    app: AppSettings = Field(default_factory=AppSettings)

    # -- derived helpers --------------------------------------------------------------
    @property
    def active_model(self) -> str:
        return self.openrouter.model if self.provider == "openrouter" else self.ollama.model


class ConfigManager:
    """Loads/saves config.json and resolves secrets (secret store first, then dev environment)."""

    def __init__(self, path: Path | None = None, secrets: SecretStore | None = None) -> None:
        self.path = path or paths.config_path()
        self.secrets = secrets or default_secret_store()
        self._lock = threading.RLock()
        self.config = self._load()

    # -- persistence ------------------------------------------------------------------
    def _load(self) -> AppConfig:
        if self.path.is_file():
            try:
                return AppConfig.model_validate(json.loads(self.path.read_text(encoding="utf-8")))
            except (ValueError, ValidationError) as exc:
                log.error("config.json is invalid (%s); keeping a backup and using defaults", exc)
                try:
                    self.path.replace(self.path.with_suffix(".json.bak"))
                except OSError:
                    pass
        return AppConfig()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(self.config.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def update(self, **sections) -> AppConfig:
        """Apply nested updates, e.g. ``update(provider="ollama")`` or ``update(review={"depth": "deep"})``."""
        with self._lock:
            data = self.config.model_dump()
            for key, value in sections.items():
                if isinstance(value, dict) and isinstance(data.get(key), dict):
                    data[key].update(value)
                else:
                    data[key] = value
            self.config = AppConfig.model_validate(data)
            self.save()
            return self.config

    # -- secrets ----------------------------------------------------------------------
    def get_github_token(self) -> str | None:
        return self.secrets.get(self.config.github.token_ref) or os.environ.get("GITHUB_TOKEN") or None

    def set_github_token(self, token: str) -> None:
        """Personal access token (manual fallback to OAuth sign-in)."""
        self.secrets.set(self.config.github.token_ref, token.strip())
        self.secrets.delete(GITHUB_REFRESH_REF)
        self.update(github={"auth_method": "pat", "oauth_scopes": "", "token_expires_at": None})

    def clear_github_token(self) -> None:
        self.secrets.delete(self.config.github.token_ref)
        self.secrets.delete(GITHUB_REFRESH_REF)
        self.update(github={"auth_method": "", "oauth_scopes": "", "token_expires_at": None})

    def get_github_refresh_token(self) -> str | None:
        return self.secrets.get(GITHUB_REFRESH_REF)

    def set_github_oauth(self, access_token: str, *, scopes: str, refresh_token: str | None,
                         expires_at: float | None) -> None:
        self.secrets.set(self.config.github.token_ref, access_token)
        if refresh_token:
            self.secrets.set(GITHUB_REFRESH_REF, refresh_token)
        else:
            self.secrets.delete(GITHUB_REFRESH_REF)
        self.update(github={"auth_method": "oauth", "oauth_scopes": scopes, "token_expires_at": expires_at})

    def effective_oauth_client_id(self) -> str:
        return (self.config.github.oauth_client_id or os.environ.get("ZEROPULSE_GITHUB_CLIENT_ID") or DEFAULT_GITHUB_CLIENT_ID).strip()

    def get_openrouter_key(self) -> str | None:
        return self.secrets.get(self.config.openrouter.api_key_ref) or os.environ.get("OPENROUTER_API_KEY") or None

    def set_openrouter_key(self, key: str) -> None:
        self.secrets.set(self.config.openrouter.api_key_ref, key.strip())

    def clear_openrouter_key(self) -> None:
        self.secrets.delete(self.config.openrouter.api_key_ref)


def load_environment() -> None:
    """Load a development .env (never overrides real environment variables)."""
    load_dotenv()
    env_url = os.environ.get("OLLAMA_BASE_URL")
    if env_url:
        log.info("OLLAMA_BASE_URL provided via environment")
