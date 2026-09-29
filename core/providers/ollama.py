"""Local Ollama provider (OpenAI-compatible endpoint; native API for model discovery)."""
from __future__ import annotations

import logging

import httpx
import openai

from .base import GenerationResult, HealthStatus, LLMProvider, ModelInfo, ProviderConfig, ProviderError
from .openai_compat import chat_completion

log = logging.getLogger(__name__)
PLACEHOLDER_KEY = "ollama"  # the SDK requires a non-empty key; Ollama ignores it


class OllamaProvider(LLMProvider):
    name = "ollama"
    hosted = False

    def __init__(self, config: ProviderConfig, *, http_client: httpx.Client | None = None,
                 sdk_client: openai.OpenAI | None = None) -> None:
        super().__init__(config)
        self._http = http_client or httpx.Client(timeout=5.0)
        self._client = sdk_client

    @property
    def native_base(self) -> str:
        base = self.config.base_url.rstrip("/")
        return base[:-3] if base.endswith("/v1") else base

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            self._client = openai.OpenAI(base_url=self.config.base_url, api_key=self.config.api_key or PLACEHOLDER_KEY,
                                         timeout=self.config.timeout, max_retries=0)
        return self._client

    def _get(self, path: str) -> httpx.Response:
        try:
            return self._http.get(f"{self.native_base}{path}")
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "Ollama did not respond in time.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable",
                                f"Ollama is not reachable at {self.native_base}. Start Ollama (ollama serve) or fix the endpoint.",
                                retryable=True) from exc

    def connect(self) -> None:
        r = self._get("/api/version")
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"Ollama responded with HTTP {r.status_code}.")

    def list_models(self) -> list[ModelInfo]:
        r = self._get("/api/tags")
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"Ollama model list failed (HTTP {r.status_code}).")
        try:
            models = r.json().get("models", [])
        except ValueError as exc:
            raise ProviderError("unavailable", "Ollama returned an unreadable model list.") from exc
        return [ModelInfo(id=m.get("name") or m.get("model", ""), name=m.get("name", ""), is_free=True,
                          context_length=None, supports_structured_output=True) for m in models]

    def get_model_info(self, model: str | None = None) -> ModelInfo | None:
        mid = model or self.config.model
        installed = {m.id: m for m in self.list_models()}
        info = installed.get(mid) or installed.get(f"{mid}:latest")
        if info is None:
            return None
        # Context is user-configured for local inference (not fixed by the model file).
        info.context_length = self.config.context_length
        return info

    def supports_structured_output(self, model: str | None = None) -> bool:
        return True  # Ollama honours response_format=json_object; failures downgrade automatically

    def health_check(self) -> HealthStatus:
        try:
            self.connect()
            models = self.list_models()
        except ProviderError as exc:
            return HealthStatus(False, exc.message, {"kind": exc.kind})
        names = [m.id for m in models]
        if not names:
            return HealthStatus(False, "Ollama is running but has no models installed. Run: ollama pull "
                                f"{self.config.model}", {"kind": "model_not_found"})
        if self.config.model not in names and f"{self.config.model}:latest" not in names:
            return HealthStatus(False, f"Model '{self.config.model}' is not installed in Ollama. Installed: "
                                f"{', '.join(names[:8])}. ZeroPulse never downloads models for you.", {"kind": "model_not_found"})
        return HealthStatus(True, f"Ollama reachable; {self.config.model} is installed.", {"models": names})

    def generate(self, messages: list[dict[str, str]], *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float | None = None) -> GenerationResult:
        extra = {"options": {"num_ctx": self.config.context_length}} if self.config.context_length else None
        return chat_completion(self, self.client, messages, json_mode=json_mode, max_tokens=max_tokens,
                               temperature=temperature, extra_body=extra)
