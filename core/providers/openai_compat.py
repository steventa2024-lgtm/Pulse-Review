"""Shared OpenAI-SDK based generation with uniform error mapping and retries."""
from __future__ import annotations

import logging
import time
from typing import Any

import openai

from .base import GenerationResult, LLMProvider, ProviderError

log = logging.getLogger(__name__)


def map_openai_error(exc: Exception) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return ProviderError("auth", "The provider rejected the API key (invalid, expired or lacking access).")
    if isinstance(exc, openai.RateLimitError):
        return rate_limit_error(exc)
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("timeout", "The model did not answer before the timeout. Increase the timeout or use a smaller context.", retryable=True)
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("unavailable", f"Could not reach the provider endpoint: {exc}", retryable=True)
    if isinstance(exc, openai.NotFoundError):
        return ProviderError("model_not_found", "The selected model was not found at the provider (it may have been removed).")
    if isinstance(exc, openai.BadRequestError):
        msg = str(exc)
        low = msg.lower()
        if "context" in low and ("length" in low or "window" in low or "maximum" in low or "exceed" in low) or "too many tokens" in low:
            return ProviderError("context_length", "The prompt exceeds the model's context window.")
        if "response_format" in low or "json_schema" in low or "json_object" in low or "structured" in low:
            return ProviderError("unsupported_format", "The model does not support JSON response mode.")
        return ProviderError("bad_request", f"The provider rejected the request: {msg[:300]}")
    if isinstance(exc, openai.InternalServerError):
        return ProviderError("unavailable", "The provider reported an internal error / is unavailable.", retryable=True)
    if isinstance(exc, openai.APIStatusError):
        code = getattr(exc, "status_code", 0)
        if code in (502, 503, 504):
            return ProviderError("unavailable", f"Provider temporarily unavailable (HTTP {code}).", retryable=True)
        if code in (401, 403):
            return ProviderError("auth", "The provider rejected the API key.")
        if code == 402:
            return ProviderError("paid_model", "The provider requires payment for this request; PulseReview only uses free models.")
        if code == 429:
            return ProviderError("rate_limit", "Rate limit reached.", retryable=True)
        return ProviderError("unknown", f"Provider error HTTP {code}: {str(exc)[:300]}")
    return ProviderError("unknown", f"Unexpected provider error: {exc}")


def _retry_after(exc: Exception) -> float | None:
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    for key in ("retry-after", "x-ratelimit-reset-after"):
        val = headers.get(key) if hasattr(headers, "get") else None
        try:
            if val is not None:
                return max(0.0, float(val))
        except ValueError:
            pass
    reset = headers.get("x-ratelimit-reset") if hasattr(headers, "get") else None
    try:
        if reset:  # epoch milliseconds (OpenRouter)
            return max(0.0, float(reset) / 1000 - time.time())
    except ValueError:
        pass
    return None


def rate_limit_error(exc: Exception) -> ProviderError:
    text = str(exc).lower()
    if "per-day" in text or "per day" in text or "daily" in text:
        err = ProviderError("rate_limit", "You've used today's free OpenRouter requests for your account. The limit resets daily "
                                          "(adding a small credit balance to OpenRouter raises it), or switch to local Ollama.")
        err.retryable = False
        return err
    err = ProviderError("rate_limit", "This free model is busy right now (OpenRouter is throttling it). PulseReview retried a few times. "
                                      "Try again in a minute or pick another ★ model — popular models like Qwen are throttled most.",
                        retryable=True)
    err.retry_after = _retry_after(exc)  # type: ignore[attr-defined]
    return err


RATE_LIMIT_RETRIES = 4
MAX_RATE_WAIT = 30.0


def chat_completion(provider: LLMProvider, client: openai.OpenAI, messages: list[dict[str, str]], *,
                    json_mode: bool, max_tokens: int | None, temperature: float | None,
                    extra_body: dict[str, Any] | None = None) -> GenerationResult:
    """One logical generation with retry on transient errors and JSON-mode downgrade."""
    cfg = provider.config
    kwargs: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature if temperature is None else temperature,
        "max_tokens": max_tokens or cfg.max_output_tokens,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    use_json = json_mode
    attempt = 0
    while True:
        call = dict(kwargs)
        if use_json:
            call["response_format"] = {"type": "json_object"}
        try:
            resp = client.chat.completions.create(**call)
        except Exception as exc:  # noqa: BLE001 - mapped below
            err = map_openai_error(exc)
            if err.kind in ("unsupported_format", "bad_request") and use_json:
                log.info("Model rejected JSON mode; retrying with prompt-only JSON")
                use_json = False
                continue
            limit = max(cfg.max_retries, RATE_LIMIT_RETRIES) if err.kind == "rate_limit" else cfg.max_retries
            if err.retryable and attempt < limit:
                wait = getattr(err, "retry_after", None)
                if wait is None:
                    wait = cfg.retry_backoff * (2 ** attempt) * (2 if err.kind == "rate_limit" else 1)
                time.sleep(min(wait, MAX_RATE_WAIT))
                attempt += 1
                continue
            raise err from exc
        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        text = (choice.message.content if choice and choice.message else None) or ""
        if not text.strip():
            if attempt < cfg.max_retries:
                time.sleep(cfg.retry_backoff * (2 ** attempt))
                attempt += 1
                continue
            raise ProviderError("empty_response", "The model returned an empty response.")
        usage = getattr(resp, "usage", None)
        return GenerationResult(
            text=text,
            model=getattr(resp, "model", None) or cfg.model,
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            finish_reason=getattr(choice, "finish_reason", None),
        )
