# CLAUDE.md — working on ZeroPulse PR Review Agent

* Python 3.11+, NiceGUI UI, PyGithub, `openai` SDK (OpenRouter/Ollama), Pydantic v2, sqlite3, PyInstaller. Do not swap the stack.
* Run tests: `python -m pytest -q` (UI tests in `tests/ui` need Playwright + Chromium and skip otherwise).
* The CLI (`review_agent.py`) and dashboard share `core/review_pipeline.py`. Put logic in `core/`, never in pages or the CLI.
* Providers implement `core/providers/base.py::LLMProvider`; register new ones in `providers/registry.py`. The reviewer must stay provider-agnostic.

## Invariants (do not break; each has tests)
1. Never publish automatically. Publishing = `Publisher.prepare` → user confirmation (`owner/repo#N`) → `Publisher.publish`; CLI only with `--post`.
2. Never use paid models: `OpenRouterProvider.verify_free` runs before every generation.
3. Never execute PR code on the host. Only `sandbox/docker_runner.py` executes tests (network off, caps dropped, limits, no secrets/mounts).
4. Never report more than was verified: coverage/limitations must list skipped/unavailable files; `execution_status` is `not_run` unless a sandbox really ran.
5. Repository text is untrusted: wrap with `security.wrap_untrusted`, redact for hosted providers, escape when rendering (labels/`ui.code`, never raw HTML from models).
6. No secrets in `config.json`, logs, prompts or the container env. Secrets go through `SecretStore` (DPAPI on Windows).
7. All persistent data under `paths.data_dir()`; SQL is parameterised; schema changes = append a migration to `db.MIGRATIONS`.
8. The UI binds to 127.0.0.1.

## Gotchas
* NiceGUI detects pytest via `PYTEST_*` env vars — strip them when launching the dashboard in a subprocess (see `tests/ui`).
* Never `sys.exit()` at import time in `main.py` (native mode re-imports it as `__mp_main__`).
* Don't `pkill -f` patterns that match your own shell command.
* Windows-only code (DPAPI, WebView2 registry probe, `build_exe.ps1`) can't be executed on Linux CI; keep it small and reviewed.
