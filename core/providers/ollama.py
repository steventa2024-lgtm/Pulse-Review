"""Local Ollama provider (OpenAI-compatible endpoint; native API for model discovery)."""
from __future__ import annotations

import logging

import httpx
import openai

import json
from dataclasses import dataclass
from typing import Callable

from .base import GenerationResult, HealthStatus, LLMProvider, ModelInfo, ProviderConfig, ProviderError
from .openai_compat import chat_completion

log = logging.getLogger(__name__)
PLACEHOLDER_KEY = "ollama"  # the SDK requires a non-empty key; Ollama ignores it


@dataclass(frozen=True)
class SuggestedModel:
    name: str
    size_gb: float
    note: str

    @property
    def fits_8gb(self) -> bool:
        return self.size_gb <= 7.0


# Code-capable models from the Ollama library, smallest first. Sizes are the approximate download size.
SUGGESTED_MODELS: list[SuggestedModel] = [
    SuggestedModel("qwen2.5-coder:7b", 4.7, "Fast code model; fits fully on an 8 GB GPU"),
    SuggestedModel("llama3.1:8b", 4.9, "General model, good explanations"),
    SuggestedModel("qwen3:8b", 5.2, "General reasoning model"),
    SuggestedModel("codellama:13b", 7.4, "Meta's code model"),
    SuggestedModel("gemma3:12b", 8.1, "Google general model"),
    SuggestedModel("deepseek-coder-v2:16b", 8.9, "Strong code model (MoE)"),
    SuggestedModel("qwen2.5-coder:14b", 9.0, "Stronger code model; partly on CPU with 8 GB VRAM"),
    SuggestedModel("gpt-oss:20b", 14.0, "OpenAI open-weight reasoning model"),
    SuggestedModel("devstral:24b", 14.0, "Mistral agentic coding model"),
    SuggestedModel("qwen3-coder:30b", 19.0, "Best code quality here; slow on 8 GB VRAM"),
]


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

    def pull_model(self, name: str, on_progress: Callable[[str, float | None], None] | None = None,
                   cancel=None) -> None:  # noqa: ANN001
        """Download a model through Ollama (only when the user explicitly asks). Streams progress (status, 0..1)."""
        name = (name or "").strip()
        if not name or any(c.isspace() for c in name) or len(name) > 200:
            raise ProviderError("bad_request", "Enter a valid model name, e.g. qwen2.5-coder:7b")
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=None)) as client, \
                    client.stream("POST", f"{self.native_base}/api/pull", json={"model": name, "stream": True}) as r:
                if r.status_code >= 400:
                    raise ProviderError("model_not_found", f"Ollama could not download '{name}' (HTTP {r.status_code}).")
                for line in r.iter_lines():
                    if cancel is not None and cancel.is_set():
                        raise ProviderError("bad_request", "Download cancelled.")
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("error"):
                        raise ProviderError("model_not_found", f"Ollama: {ev['error']}")
                    total, done = ev.get("total"), ev.get("completed")
                    frac = (done / total) if total and done is not None else None
                    if on_progress:
                        on_progress(str(ev.get("status", "")), frac)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "Ollama stopped responding during the download.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"Ollama is not reachable at {self.native_base}.") from exc

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
                                f"{', '.join(names[:8])}. PulseReview never downloads models for you.", {"kind": "model_not_found"})
        return HealthStatus(True, f"Ollama reachable; {self.config.model} is installed.", {"models": names})

    def generate(self, messages: list[dict[str, str]], *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float | None = None) -> GenerationResult:
        extra = {"options": {"num_ctx": self.config.context_length}} if self.config.context_length else None
        return chat_completion(self, self.client, messages, json_mode=json_mode, max_tokens=max_tokens,
                               temperature=temperature, extra_body=extra)
