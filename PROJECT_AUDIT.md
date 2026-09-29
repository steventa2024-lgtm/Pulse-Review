# PROJECT_AUDIT — ZeroPulse PR Review Agent

_Audit date: 2026-09-29. Audited branch: `claude/ecstatic-ramanujan-qz4m34`._

## 1. Existing functionality

**None.** The repository `steventa2024-lgtm/Pulse-Review` contains no commits and no
remote branches (`git ls-remote origin` returns nothing). There is no `review_agent.py`,
no dependency manifest, no GitHub authentication logic, no LLM integration, no diff
retrieval, no tests and no packaging configuration.

Because there is no prior implementation, "preserving the existing CLI" means
implementing exactly the CLI surface named in the specification
(`--dry-run`, `--post`, `--model`, plus `--provider`, `--generate-tests`, `--output`, `--json`).
No user changes exist that could be overwritten.

## 2. Broken or incomplete functionality

Not applicable (nothing exists). Everything is built new.

## 3. Reusable components

None from the repo. Reused third-party building blocks: NiceGUI (UI + FastAPI server),
PyGithub, the `openai` SDK (OpenAI-compatible client for OpenRouter and Ollama),
Pydantic, httpx, sqlite3, PyInstaller.

## 4. Implementation plan

| Phase | Deliverable | Verification |
|------|-------------|--------------|
| 2 Foundation | `core/paths.py`, `config.py`, `security.py`, `db.py`, logging | unit tests |
| 3 Providers | `core/providers/*` (OpenRouter free-only, Ollama), JSON validation | mocked SDK tests |
| 4 GitHub | `github_client.py`, `diff_parser.py` | fake-PyGithub tests, fixtures |
| 5 Review | `context_builder.py`, `reviewer.py`, `review_pipeline.py`, static checks | mocked-LLM pipeline tests |
| 6 Test gen | `test_generator.py` | unit tests |
| 7 Sandbox | `core/sandbox/*` (Docker, network-off, limits) | command-construction tests + Docker if available |
| 8 Dashboard | NiceGUI pages | rendered in headless Chromium |
| 9 Watch | polling with ETag, SQLite persistence | unit tests |
| 10 Publish | publishing, stale/duplicate protection | unit tests |
| 11 Packaging | `main.py`, `build_exe.ps1` | **cannot be executed on this Linux host** |
| 12 Docs | README, ARCHITECTURE, CLAUDE.md | — |

## 5. Dependencies and blockers

The build environment is a **Linux container**, not Windows 10/11 with PowerShell 5.1. Consequences:

- `build_exe.ps1` and `dist/ZeroPulsePRReview.exe` **cannot be built or run here**. PyInstaller
  does not cross-compile. Status: **BLOCKED** (script authored, not executed).
- Windows DPAPI secret storage is implemented with `ctypes` but can only be exercised on Windows.
  A `0600` file fallback is used on non-Windows hosts for development only.
- Native window mode (pywebview / WebView2) cannot be launched here; a browser fallback exists.
- No GitHub token, OpenRouter key, or Ollama instance is available to this session, so live
  integration tests (real PR, real model, real publishing) are **BLOCKED**, not simulated.
- Files are created with the editor tool rather than PowerShell here-strings (Linux host);
  all files are UTF-8.
