import json

import httpx
import openai
import pytest

from core.config import AppConfig, ConfigManager
from core.providers import ProviderError, available_providers, create_provider, extract_json
from core.providers.base import ProviderConfig
from core.providers.ollama import OllamaProvider
from core.providers.openrouter import OpenRouterProvider, parse_model
from core.providers.registry import register_provider
from core.security import MemorySecretStore

CATALOG = {"data": [
    {"id": "qwen/qwen3-coder:free", "name": "Qwen3 Coder", "context_length": 262144,
     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format", "temperature"]},
    {"id": "google/gemma-3-27b-it:free", "context_length": 96000, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["temperature"]},
    {"id": "openai/gpt-4o", "context_length": 128000, "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
    {"id": "sneaky/free-looking:free", "context_length": 8000, "pricing": {"prompt": "0", "completion": "0.000001"}},
]}


def _cfg(model="qwen/qwen3-coder:free", key="sk-or-v1-" + "k" * 30):
    return ProviderConfig(provider="openrouter", base_url="https://openrouter.ai/api/v1", model=model, api_key=key, max_retries=1, retry_backoff=0)


def _or(model="qwen/qwen3-coder:free", sdk=None, handler=None, key="sk-or-v1-" + "k" * 30):
    handler = handler or (lambda req: httpx.Response(200, json=CATALOG))
    return OpenRouterProvider(_cfg(model, key), http_client=httpx.Client(transport=httpx.MockTransport(handler)), sdk_client=sdk)


class FakeSDK:
    """Mimics openai.OpenAI().chat.completions.create with scripted outcomes."""
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.calls.append(kw)
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        from types import SimpleNamespace as NS
        return NS(model=kw["model"], choices=[NS(message=NS(content=o), finish_reason="stop")],
                  usage=NS(prompt_tokens=11, completion_tokens=7))


def _err(cls, status=400, msg="x"):
    req = httpx.Request("POST", "https://x")
    if cls is openai.APITimeoutError:
        return cls(request=req)
    if cls is openai.APIConnectionError:
        return cls(request=req)
    return cls(msg, response=httpx.Response(status, request=req), body=None)


# ------------------------------------------------------------------ catalog / free-only guarantees
def test_catalog_identifies_only_truly_free_models():
    p = _or()
    free = {m.id for m in p.list_models()}
    assert free == {"qwen/qwen3-coder:free", "google/gemma-3-27b-it:free"}
    assert "sneaky/free-looking:free" not in free  # completion price non-zero
    info = p.get_model_info()
    assert info.context_length == 262144 and info.supports_structured_output is True  # from metadata, not assumed
    assert p.get_model_info("google/gemma-3-27b-it:free").supports_structured_output is False
    assert p.effective_context_length() == 262144  # no user cap configured → provider metadata


def test_candidate_status_marks_unavailable_models():
    cands = {m.id: m for m in _or().candidate_status()}
    assert cands["qwen/qwen3-coder:free"].available
    assert not cands["deepseek/deepseek-chat-v3.1:free"].available and cands["deepseek/deepseek-chat-v3.1:free"].note


def test_paid_model_is_refused_never_silently_used():
    sdk = FakeSDK(["{}"])
    p = _or(model="openai/gpt-4o", sdk=sdk)
    with pytest.raises(ProviderError) as e:
        p.generate([{"role": "user", "content": "hi"}])
    assert e.value.kind == "paid_model" and sdk.calls == []
    p2 = _or(model="sneaky/free-looking:free", sdk=sdk)
    with pytest.raises(ProviderError) as e2:
        p2.generate([{"role": "user", "content": "hi"}])
    assert e2.value.kind == "paid_model" and sdk.calls == []
    p3 = _or(model="nope/missing", sdk=sdk)
    with pytest.raises(ProviderError) as e3:
        p3.generate([{"role": "user", "content": "hi"}])
    assert e3.value.kind == "model_not_found"


def test_generate_uses_json_mode_only_when_supported_and_reports_real_usage():
    sdk = FakeSDK(['{"a": 1}', '{"a": 2}'])
    r = _or(sdk=sdk).generate([{"role": "user", "content": "x"}], json_mode=True)
    assert sdk.calls[0]["response_format"] == {"type": "json_object"} and r.input_tokens == 11 and r.output_tokens == 7
    sdk2 = FakeSDK(['{"a": 1}'])
    _or(model="google/gemma-3-27b-it:free", sdk=sdk2).generate([{"role": "user", "content": "x"}], json_mode=True)
    assert "response_format" not in sdk2.calls[0]


def test_json_mode_rejection_downgrades_once():
    sdk = FakeSDK([_err(openai.BadRequestError, 400, "response_format json_object unsupported"), '{"ok": true}'])
    r = _or(sdk=sdk).generate([{"role": "user", "content": "x"}], json_mode=True)
    assert r.text == '{"ok": true}' and "response_format" not in sdk.calls[1]


@pytest.mark.parametrize("exc,kind", [
    (_err(openai.AuthenticationError, 401), "auth"),
    (_err(openai.RateLimitError, 429), "rate_limit"),
    (_err(openai.APITimeoutError), "timeout"),
    (_err(openai.APIConnectionError), "unavailable"),
    (_err(openai.BadRequestError, 400, "This model's maximum context length is 8192 tokens"), "context_length"),
    (_err(openai.NotFoundError, 404), "model_not_found"),
    (_err(openai.InternalServerError, 500), "unavailable"),
])
def test_openrouter_error_mapping(exc, kind):
    sdk = FakeSDK([exc] * 6)
    with pytest.raises(ProviderError) as e:
        _or(sdk=sdk).generate([{"role": "user", "content": "x"}])
    assert e.value.kind == kind and e.value.message


def test_retry_then_success_on_rate_limit():
    sdk = FakeSDK([_err(openai.RateLimitError, 429), "done"])
    assert _or(sdk=sdk).generate([{"role": "user", "content": "x"}]).text == "done"
    assert len(sdk.calls) == 2


def test_empty_response_is_an_error_not_success():
    sdk = FakeSDK(["", "  ", ""])
    with pytest.raises(ProviderError) as e:
        _or(sdk=sdk).generate([{"role": "user", "content": "x"}])
    assert e.value.kind == "empty_response"


def test_missing_key_and_bad_key():
    with pytest.raises(ProviderError) as e:
        _or(key=None).connect()
    assert e.value.kind == "auth"
    p = _or(handler=lambda req: httpx.Response(401 if req.url.path.endswith("/key") else 200, json=CATALOG))
    with pytest.raises(ProviderError) as e2:
        p.connect()
    assert e2.value.kind == "auth"
    h = _or(handler=lambda req: httpx.Response(401 if req.url.path.endswith("/key") else 200, json=CATALOG)).health_check()
    assert not h.ok and "rejected" in h.message


def test_catalog_unavailable_and_timeout():
    def boom(req):
        raise httpx.ConnectError("down")
    with pytest.raises(ProviderError) as e:
        _or(handler=boom).list_models()
    assert e.value.kind == "unavailable"

    def slow(req):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(ProviderError) as e2:
        _or(handler=slow).list_models()
    assert e2.value.kind == "timeout"
    with pytest.raises(ProviderError):
        _or(handler=lambda r: httpx.Response(500)).list_models()


def test_config_repr_hides_key():
    assert "sk-or-v1" not in repr(_cfg())


# ------------------------------------------------------------------ Ollama
def _ol(handler, sdk=None, model="qwen3-coder:30b"):
    cfg = ProviderConfig(provider="ollama", base_url="http://localhost:11434/v1", model=model, context_length=16384)
    return OllamaProvider(cfg, http_client=httpx.Client(transport=httpx.MockTransport(handler)), sdk_client=sdk)


def test_ollama_discovery_and_health():
    def h(req):
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5"})
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3-coder:30b"}, {"name": "llama3:latest"}]})
        return httpx.Response(404)
    p = _ol(h)
    assert not p.hosted and [m.id for m in p.list_models()] == ["qwen3-coder:30b", "llama3:latest"]
    assert p.health_check().ok
    assert p.get_model_info().context_length == 16384  # configured, not assumed
    assert not _ol(h, model="missing:7b").health_check().ok
    assert "never downloads" in _ol(h, model="missing:7b").health_check().message


def test_ollama_unreachable_gives_clear_message():
    def refuse(req):
        raise httpx.ConnectError("refused")
    hs = _ol(refuse).health_check()
    assert not hs.ok and "not reachable" in hs.message and "Start Ollama" in hs.message
    with pytest.raises(ProviderError) as e:
        _ol(refuse).connect()
    assert e.value.kind == "unavailable"


def test_ollama_no_models_installed():
    def h(req):
        return httpx.Response(200, json={"version": "1"} if "version" in req.url.path else {"models": []})
    assert "no models" in _ol(h).health_check().message


def test_ollama_generate_passes_context_and_placeholder_key():
    sdk = FakeSDK(['{"x": 1}'])
    p = _ol(lambda r: httpx.Response(200, json={}), sdk=sdk)
    p.generate([{"role": "user", "content": "hi"}], json_mode=True)
    assert sdk.calls[0]["extra_body"] == {"options": {"num_ctx": 16384}}
    real = OllamaProvider(ProviderConfig(provider="ollama", base_url="http://localhost:11434/v1", model="m"))
    assert real.client.api_key == "ollama"  # SDK-required placeholder, no paid key


# ------------------------------------------------------------------ registry / switching
def test_provider_selection_and_switching_needs_no_other_changes():
    mgr = ConfigManager(None or __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "c.json", MemorySecretStore())
    mgr.set_openrouter_key("k" * 20)
    p1 = create_provider(mgr.config, mgr)
    assert p1.name == "openrouter" and p1.model == "qwen/qwen3-coder:free" and p1.hosted
    mgr.update(provider="ollama")
    p2 = create_provider(mgr.config, mgr)
    assert p2.name == "ollama" and p2.model == "qwen3-coder:30b" and not p2.hosted
    assert create_provider(mgr.config, mgr, provider="openrouter", model="google/gemma-3-27b-it:free").model == "google/gemma-3-27b-it:free"
    with pytest.raises(ProviderError):
        create_provider(mgr.config, mgr, provider="nonesuch")
    assert available_providers() == ["ollama", "openrouter"]


def test_registry_is_extensible_for_llamacpp():
    class Dummy(OllamaProvider):
        name = "llamacpp"
    register_provider("llamacpp", Dummy)
    from core.providers import registry
    try:
        assert "llamacpp" in available_providers()
    finally:
        registry.PROVIDERS.pop("llamacpp")


# ------------------------------------------------------------------ JSON extraction
@pytest.mark.parametrize("text", [
    '{"a": 1}', '```json\n{"a": 1}\n```', 'Sure! Here you go:\n{"a": 1}\nHope that helps',
    '<think>let me {think}</think>{"a": 1}', 'noise {bad json} then {"a": 1}',
    '{"a": "brace } inside string"}',
])
def test_extract_json_variants(text):
    assert "a" in extract_json(text)


@pytest.mark.parametrize("text", ["", "   ", "no json here", "{unterminated"])
def test_extract_json_failures(text):
    with pytest.raises(ValueError):
        extract_json(text)


def test_parse_model_free_detection_edge_cases():
    assert parse_model({"id": "a", "pricing": {"prompt": "0", "completion": "0", "image": "0"}}).is_free
    assert not parse_model({"id": "a", "pricing": {"prompt": "0", "completion": "0", "request": "0.01"}}).is_free
    assert not parse_model({"id": "a"}).is_free
    assert not parse_model({"id": "a", "pricing": {"prompt": "-1", "completion": "0"}}).is_free


def test_review_models_filters_non_text_and_unsuitable_and_ranks_code_first():
    cat = {"data": [
        {"id": "google/lyria-3-clip-preview", "context_length": 1048576, "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"input_modalities": ["text"], "output_modalities": ["audio"]}},
        {"id": "nvidia/nemotron-3.5-content-safety:free", "context_length": 128000, "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "liquid/tiny:free", "context_length": 8192, "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "google/gemma-4-31b-it:free", "context_length": 262144, "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"modality": "text+image->text"}},
        {"id": "qwen/qwen3.8-27b:free", "context_length": 262144, "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "cohere/north-mini-code:free", "context_length": 256000, "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "openai/gpt-5", "context_length": 400000, "pricing": {"prompt": "0.00001", "completion": "0.00003"}},
    ]}
    p = _or(handler=lambda req: httpx.Response(200, json=cat))
    ids = [m.id for m in p.review_models()]
    assert ids == ["cohere/north-mini-code:free", "qwen/qwen3.8-27b:free", "google/gemma-4-31b-it:free"]
    assert all(m.recommended for m in p.review_models()[:3])


def test_rate_limit_retries_more_and_honours_retry_after(monkeypatch):
    import core.providers.openai_compat as oc
    slept = []
    monkeypatch.setattr(oc.time, "sleep", slept.append)
    req = httpx.Request("POST", "https://x")
    e = openai.RateLimitError("rate limited upstream", response=httpx.Response(429, request=req, headers={"retry-after": "3"}), body=None)
    sdk = FakeSDK([e, e, e, "ok"])
    assert _or(sdk=sdk).generate([{"role": "user", "content": "x"}]).text == "ok"
    assert slept == [3.0, 3.0, 3.0]


def test_daily_free_quota_is_not_retried_and_explained(monkeypatch):
    import core.providers.openai_compat as oc
    monkeypatch.setattr(oc.time, "sleep", lambda s: None)
    req = httpx.Request("POST", "https://x")
    e = openai.RateLimitError("Rate limit exceeded: free-models-per-day", response=httpx.Response(429, request=req), body=None)
    sdk = FakeSDK([e, "never"])
    with pytest.raises(ProviderError) as err:
        _or(sdk=sdk).generate([{"role": "user", "content": "x"}])
    assert "today's free" in err.value.message and len(sdk.calls) == 1


def test_ollama_pull_streams_progress_and_reports_errors(monkeypatch):
    import json as _json
    from core.providers import ollama as om
    events = [{"status": "pulling manifest"}, {"status": "downloading", "total": 100, "completed": 40},
              {"status": "downloading", "total": 100, "completed": 100}, {"status": "success"}]
    body = "\n".join(_json.dumps(e) for e in events).encode()
    seen_req = {}

    def handler(req):
        seen_req["path"], seen_req["json"] = req.url.path, _json.loads(req.content)
        return httpx.Response(200, content=body)

    real_client = httpx.Client
    monkeypatch.setattr(om.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    p = OllamaProvider(ProviderConfig(provider="ollama", base_url="http://localhost:11434/v1", model="m"))
    got = []
    p.pull_model("qwen2.5-coder:7b", lambda s, f: got.append((s, f)))
    assert seen_req == {"path": "/api/pull", "json": {"model": "qwen2.5-coder:7b", "stream": True}}
    assert got[1] == ("downloading", 0.4) and got[-1] == ("success", None)
    err = _json.dumps({"error": "pull model manifest: file does not exist"}).encode()
    monkeypatch.setattr(om.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=err))))
    with pytest.raises(ProviderError) as e:
        p.pull_model("nope:1b")
    assert "does not exist" in e.value.message
    with pytest.raises(ProviderError):
        p.pull_model("bad name")
    assert om.SUGGESTED_MODELS[0].fits_8gb and not om.SUGGESTED_MODELS[-1].fits_8gb
