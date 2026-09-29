# Architecture

```
review_agent.py (CLI) ─┐                       ┌─ dashboard/ (NiceGUI pages, jobs, context)
main.py (desktop) ─────┼─▶ core/services.py ◀──┘
                       │      (composition root: config → GitHub client, provider, pipeline, publisher, watcher, sandbox)
                       ▼
core/review_pipeline.py ── stages ──▶ github_client → context_builder/diff_parser → static_checks → reviewer (+providers)
                                       → verify_issues → test_generator → sandbox → db
core/publisher.py  (prepare → confirm → publish; stale + duplicate protection)      core/watcher.py (polling + ETag)
```

One pipeline serves both the CLI and the dashboard; neither contains review logic.

## Modules

| Module | Responsibility |
|---|---|
| `paths.py` | `%APPDATA%\ZeroPulse\PRReviewAgent\` layout, bundle dir (PyInstaller `_MEIPASS`), `ZEROPULSE_DATA_DIR` override |
| `config.py` | Pydantic `AppConfig` ⇄ `config.json`; secrets resolved by *reference* from the secret store (dev fallback: env/.env) |
| `security.py` | DPAPI (`ctypes`) / 0600-file secret stores, secret redaction, log filter, untrusted-data framing, safe filenames/paths |
| `db.py` | sqlite3, WAL, `PRAGMA user_version` migrations, parameterised SQL, cascading deletes |
| `schemas.py` | Strict result models + lenient LLM-input models (aliases/normalisation) |
| `providers/` | `LLMProvider` ABC (`connect/health_check/list_models/get_model_info/generate/supports_structured_output`); OpenRouter (free-only guard), Ollama, registry (extensible, e.g. llama.cpp) |
| `github_client.py` | Strict PR-URL parsing, PyGithub retrieval (lazy pagination), patch states (full/unavailable/binary), publishing, conditional polling, safe zip extraction |
| `diff_parser.py` | Unified-diff → hunks/lines with old/new numbers; `DiffIndex` for GitHub inline-comment validity (RIGHT/LEFT) |
| `context_builder.py` | Repo understanding (languages, frameworks, test setup), token-budgeted chunking with explicit per-file coverage |
| `static_checks.py` | Deterministic checks (credentials, risky patterns, Python/JSON syntax by parsing, missing tests) — never executes PR code |
| `reviewer.py` | Prompts, JSON validation with corrective retries, finding verification, dedupe, risk derivation |
| `test_generator.py` | Framework-aware test generation; path normalisation; import/symbol checks; verification flags |
| `sandbox/` | `SandboxRunner` interface, `DockerRunner`, language profiles (extension point), result parser |
| `publisher.py` | Markdown rendering, plan building (inline only for verified locations), confirmation, stale/duplicate checks |
| `watcher.py` | Watched repos, new/updated detection by head SHA |

## Key design decisions

* **Grounding over fluency.** A finding survives only if its file is in the PR and (line valid in the diff or evidence found in the diff). Wrong line numbers are relocated via evidence; suggested Python code that doesn't parse is withheld; discards are reported in *Limitations*.
* **Never claim more than was done.** Files that were binary/oversized/skipped/failed are listed with a reason; execution status only becomes `passed/failed` after a real sandbox run; `not_run` otherwise. Malformed model output fails the review after bounded retries.
* **Free-only inference.** `OpenRouterProvider.generate` re-verifies the model is zero-price in the live catalog before every call.
* **Untrusted repo content.** Wrapped in delimiters (look-alikes neutralised), system rules forbid obeying it, secrets redacted for hosted providers, credentials never enter prompts, `@mentions` neutralised before publishing.
* **Publishing safety.** `prepare()` re-fetches the PR (stale ⇒ refuse); `publish()` needs the exact `owner/repo#N`, re-checks the head SHA, refuses identical content (hash), posts `COMMENT` only, and stores review id/URL.
* **Threading.** The pipeline is synchronous; the dashboard runs it in background threads (`JobManager`) and polls progress, so jobs survive page navigation. SQLite connections are per-operation.
* **Native window.** `main.py` uses NiceGUI native mode when pywebview (+ WebView2 on Windows) is present, else browser fallback with a message. `multiprocessing.freeze_support()` runs under `__main__`; the spawned child process does nothing on import.
