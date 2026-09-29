"""OpenRouter provider restricted to verified zero-price models."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import openai

from ..config import OPENROUTER_CANDIDATES
from .base import HealthStatus, LLMProvider, ModelInfo, ProviderConfig, ProviderError, GenerationResult
from .openai_compat import chat_completion, map_openai_error

log = logging.getLogger(__name__)
_CATALOG_TTL = 600.0


def _is_zero(v: Any) -> bool:
    try:
        return float(v) == 0.0
    except (TypeError, ValueError):
        return False


def parse_model(entry: dict[str, Any]) -> ModelInfo:
    pricing = entry.get("pricing") or {}
    # free means every priced dimension that exists is zero, and prompt+completion are both explicitly zero
    free = _is_zero(pricing.get("prompt")) and _is_zero(pricing.get("completion"))
    if free:
        for k, v in pricing.items():
            if k in ("prompt", "completion", "request") or v in (None, ""):
                continue
            if k in ("image", "web_search", "internal_reasoning") and not _is_zero(v):
                free = False
        if pricing.get("request") not in (None, "") and not _is_zero(pricing.get("request")):
            free = False
    params = list(entry.get("supported_parameters") or [])
    ctx = entry.get("context_length") or (entry.get("top_provider") or {}).get("context_length")
    structured = None
    if params:
        structured = any(p in params for p in ("response_format", "structured_outputs"))
    arch = entry.get("architecture") or {}
    outs = arch.get("output_modalities")
    ins = arch.get("input_modalities")
    text_output = True
    if isinstance(outs, list) and outs:
        text_output = "text" in outs and (not isinstance(ins, list) or not ins or "text" in ins)
    elif isinstance(arch.get("modality"), str) and "->" in arch["modality"]:
        text_output = "text" in arch["modality"].split("->", 1)[1]
    return ModelInfo(id=entry.get("id", ""), name=entry.get("name", ""), context_length=ctx, is_free=free,
                     supported_parameters=params, supports_structured_output=structured, text_output=text_output)


_UNSUITABLE = ("content-safety", "guard", "safety", "embed", "moderation", "tts", "whisper", "lyria", "image")
_CODE_HINTS = ("coder", "code", "devstral", "codestral")
_STRONG_HINTS = ("qwen", "deepseek", "kimi", "glm", "gpt-oss", "llama-3.3-70b", "nemotron-3-super", "nemotron-3-ultra", "mistral")


def review_score(m: ModelInfo) -> tuple:
    """Sort key: code-specialised first, then strong general models, then by context window."""
    mid = m.id.lower()
    code = any(h in mid for h in _CODE_HINTS)
    strong = any(h in mid for h in _STRONG_HINTS)
    router = mid.startswith("openrouter/")
    return (0 if code else 1 if strong else 2, 1 if router else 0, -(m.context_length or 0), mid)


def suitable_for_review(m: ModelInfo) -> bool:
    mid = m.id.lower()
    return m.is_free and m.text_output and not any(h in mid for h in _UNSUITABLE) and (m.context_length or 16384) >= 16384


class OpenRouterProvider(LLMProvider):
    name = "openrouter"
    _catalog_cache: tuple[float, list[ModelInfo]] | None = None

    def __init__(self, config: ProviderConfig, *, http_client: httpx.Client | None = None,
                 sdk_client: openai.OpenAI | None = None) -> None:
        super().__init__(config)
        self._http = http_client or httpx.Client(timeout=min(config.timeout, 30.0))
        self._client = sdk_client
        self._catalog: tuple[float, list[ModelInfo]] | None = None

    # -- SDK client -------------------------------------------------------------------
    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            if not self.config.api_key:
                raise ProviderError("auth", "No OpenRouter API key configured. Add one in Settings → AI Provider.")
            self._client = openai.OpenAI(
                base_url=self.config.base_url, api_key=self.config.api_key,
                timeout=self.config.timeout, max_retries=0,
                default_headers={"HTTP-Referer": "https://github.com/zeropulse/pr-review-agent",
                                 "X-Title": "PulseReview"},
            )
        return self._client

    # -- catalog ----------------------------------------------------------------------
    def fetch_catalog(self, force: bool = False) -> list[ModelInfo]:
        if not force and self._catalog and time.time() - self._catalog[0] < _CATALOG_TTL:
            return self._catalog[1]
        try:
            r = self._http.get(f"{self.config.base_url.rstrip('/')}/models")
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "Timed out fetching the OpenRouter model catalog.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"Could not reach OpenRouter: {exc}", retryable=True) from exc
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"OpenRouter catalog request failed (HTTP {r.status_code}).")
        try:
            data = r.json().get("data", [])
        except ValueError as exc:
            raise ProviderError("unavailable", "OpenRouter returned an unreadable model catalog.") from exc
        models = [parse_model(e) for e in data if isinstance(e, dict) and e.get("id")]
        self._catalog = (time.time(), models)
        return models

    def list_free_models(self, force: bool = False) -> list[ModelInfo]:
        return sorted((m for m in self.fetch_catalog(force) if m.is_free), key=lambda m: m.id)

    def review_models(self, force: bool = False) -> list[ModelInfo]:
        """Verified-free, text-capable models suited to code review, best first. Top picks are marked recommended."""
        models = sorted((m for m in self.fetch_catalog(force) if suitable_for_review(m)), key=review_score)
        for m in models[:3]:
            m.recommended = True
        return models

    def candidate_status(self) -> list[ModelInfo]:
        """Preferred candidates annotated with live availability (unavailable ones stay listed but disabled)."""
        live = {m.id: m for m in self.fetch_catalog() if m.is_free}
        out: list[ModelInfo] = []
        for cid in OPENROUTER_CANDIDATES:
            if cid in live:
                out.append(live[cid])
            else:
                out.append(ModelInfo(id=cid, name=cid, available=False, is_free=False, note="Not currently offered as a free model"))
        return out

    # -- interface --------------------------------------------------------------------
    def list_models(self) -> list[ModelInfo]:
        return self.list_free_models()

    def get_model_info(self, model: str | None = None) -> ModelInfo | None:
        mid = model or self.config.model
        for m in self.fetch_catalog():
            if m.id == mid:
                return m
        return None

    def verify_free(self, model: str | None = None) -> ModelInfo:
        """Refuse to use any model that is not confirmed zero-price by the live catalog."""
        mid = model or self.config.model
        info = self.get_model_info(mid)
        if info is None:
            raise ProviderError("model_not_found", f"Model '{mid}' is not in the OpenRouter catalog. Pick another free model.")
        if not info.is_free:
            raise ProviderError("paid_model", f"Model '{mid}' is not free. PulseReview never uses paid models; choose a free one.")
        return info

    def supports_structured_output(self, model: str | None = None) -> bool:
        try:
            info = self.get_model_info(model)
        except ProviderError:
            return False
        return bool(info and info.supports_structured_output)

    def connect(self) -> None:
        if not self.config.api_key:
            raise ProviderError("auth", "No OpenRouter API key configured.")
        try:
            r = self._http.get(f"{self.config.base_url.rstrip('/')}/key",
                               headers={"Authorization": f"Bearer {self.config.api_key}"})
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "Timed out contacting OpenRouter.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"Could not reach OpenRouter: {exc}", retryable=True) from exc
        if r.status_code in (401, 403):
            raise ProviderError("auth", "OpenRouter rejected the API key.")
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"OpenRouter key check failed (HTTP {r.status_code}).")

    def health_check(self) -> HealthStatus:
        try:
            self.connect()
            info = self.verify_free()
        except ProviderError as exc:
            return HealthStatus(False, exc.message, {"kind": exc.kind})
        ctx = f"{info.context_length:,} tokens" if info.context_length else "unknown"
        return HealthStatus(True, f"OpenRouter reachable; {info.id} is free (context {ctx}).",
                            {"context_length": info.context_length, "structured": info.supports_structured_output})

    def generate(self, messages: list[dict[str, str]], *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float | None = None) -> GenerationResult:
        info = self.verify_free()  # hard guard: never call a paid model
        use_json = json_mode and bool(info.supports_structured_output)
        try:
            return chat_completion(self, self.client, messages, json_mode=use_json, max_tokens=max_tokens,
                                   temperature=temperature)
        except openai.OpenAIError as exc:  # pragma: no cover - chat_completion already maps
            raise map_openai_error(exc) from exc
