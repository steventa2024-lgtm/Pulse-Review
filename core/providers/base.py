"""Provider-agnostic inference interface."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

ErrorKind = Literal[
    "auth", "rate_limit", "unavailable", "context_length", "unsupported_format",
    "timeout", "empty_response", "paid_model", "model_not_found", "bad_request", "unknown",
]


class ProviderError(Exception):
    """A provider failure with a machine-readable ``kind`` and a user-presentable message."""

    def __init__(self, kind: ErrorKind, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message
        self.retryable = retryable


@dataclass
class ProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str | None = None  # resolved secret (never logged); may be None for Ollama
    timeout: float = 120.0
    context_length: int | None = None  # configured cap (tokens); provider metadata may be smaller/larger
    max_retries: int = 2
    retry_backoff: float = 2.0
    temperature: float = 0.1
    max_output_tokens: int = 4096
    extra: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # never leak the key
        return f"ProviderConfig(provider={self.provider!r}, model={self.model!r}, base_url={self.base_url!r})"


@dataclass
class ModelInfo:
    id: str
    name: str = ""
    context_length: int | None = None
    is_free: bool = False
    available: bool = True
    supported_parameters: list[str] = field(default_factory=list)
    supports_structured_output: bool | None = None
    note: str = ""
    text_output: bool = True  # False for image/audio/music generators, which cannot review code
    recommended: bool = False


@dataclass
class GenerationResult:
    text: str
    model: str
    input_tokens: int | None = None  # None when the provider did not report real usage
    output_tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class HealthStatus:
    ok: bool
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    name: str = "abstract"
    hosted: bool = True  # True when prompts leave the machine (redaction + private-repo consent apply)

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def connect(self) -> None:
        """Validate credentials/endpoint; raise ProviderError on failure."""

    @abstractmethod
    def health_check(self) -> HealthStatus: ...

    @abstractmethod
    def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    def get_model_info(self, model: str | None = None) -> ModelInfo | None: ...

    @abstractmethod
    def generate(self, messages: list[dict[str, str]], *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float | None = None) -> GenerationResult: ...

    @abstractmethod
    def supports_structured_output(self, model: str | None = None) -> bool: ...

    # -- shared helpers ---------------------------------------------------------------
    @property
    def model(self) -> str:
        return self.config.model

    def effective_context_length(self) -> int:
        """Actual usable context: min(provider metadata, user cap); never a hard-coded assumption."""
        info = None
        try:
            info = self.get_model_info()
        except ProviderError:
            pass
        candidates = [c for c in (info.context_length if info else None, self.config.context_length) if c]
        return min(candidates) if candidates else 8192


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Extract the first JSON object from model text (handles fences, <think> blocks, prose)."""
    if not text or not text.strip():
        raise ValueError("empty response")
    text = _THINK.sub("", text).strip()
    candidates = [text]
    candidates += [m.group(1).strip() for m in _FENCE.finditer(text)]
    for cand in candidates:
        try:
            return json.loads(cand)
        except (ValueError, TypeError):
            pass
    # balanced-brace scan for the first top-level object
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no valid JSON object found in response")
