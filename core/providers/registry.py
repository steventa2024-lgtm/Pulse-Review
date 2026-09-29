"""Provider registry. New backends (e.g. llama.cpp) register here without touching review logic."""
from __future__ import annotations

from typing import Callable

from ..config import AppConfig, ConfigManager
from .base import LLMProvider, ProviderConfig, ProviderError
from .ollama import OllamaProvider
from .openrouter import OpenRouterProvider

ProviderFactory = Callable[[ProviderConfig], LLMProvider]

PROVIDERS: dict[str, ProviderFactory] = {
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    PROVIDERS[name] = factory


def available_providers() -> list[str]:
    return sorted(PROVIDERS)


def build_provider_config(cfg: AppConfig, mgr: ConfigManager | None, provider: str | None = None,
                          model: str | None = None) -> ProviderConfig:
    name = provider or cfg.provider
    if name == "openrouter":
        s = cfg.openrouter
        return ProviderConfig(provider=name, base_url=s.base_url, model=model or s.model,
                              api_key=mgr.get_openrouter_key() if mgr else None, timeout=s.timeout,
                              context_length=cfg.review.max_context_budget)
    if name == "ollama":
        s = cfg.ollama
        return ProviderConfig(provider=name, base_url=s.base_url, model=model or s.model, api_key=None,
                              timeout=s.timeout, context_length=s.context_length)
    raise ProviderError("bad_request", f"Unknown provider '{name}'. Available: {', '.join(available_providers())}")


def create_provider(cfg: AppConfig, mgr: ConfigManager | None = None, provider: str | None = None,
                    model: str | None = None) -> LLMProvider:
    pc = build_provider_config(cfg, mgr, provider, model)
    factory = PROVIDERS.get(pc.provider)
    if factory is None:
        raise ProviderError("bad_request", f"Unknown provider '{pc.provider}'")
    return factory(pc)
