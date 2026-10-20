# PulseReview macOS port — verification report

Date: 2026-10-20. Both PRs remain drafts; no release or website deployment occurred.

## Candidate identity and download

- Application source: **68726a73d19f2b76a84193c49efa30b74c6d1e0f**, clean checkout.
- [Application PR #2](https://github.com/steventa2024-lgtm/Pulse-Review/pull/2),
  based on `claude/ecstatic-ramanujan-qz4m34`.
- [Website/infrastructure PR #3](https://github.com/steventa2024-lgtm/Pulse-Review/pull/3),
  based on `main`; these histories have no merge base.
- [Successful Apple Silicon CI](https://github.com/steventa2024-lgtm/Pulse-Review/actions/runs/39476391838),
  `macos-15`, native arm64 Python 3.11.9, job completed in 4m10s.
- [Candidate DMG and checksum artifact](https://github.com/steventa2024-lgtm/Pulse-Review/actions/runs/39476391838/artifacts/12288849317).
  This is a CI artifact with 30-day retention, not a published GitHub Release.
- [Raw verification reports](https://github.com/steventa2024-lgtm/Pulse-Review/actions/runs/39476391838/artifacts/12288859458).
- DMG: `PulseReview-macOS-arm64.dmg`, **55,226,843 bytes**. Contains `PulseReview.app`.
- SHA-256, also recomputed after download to Windows:
  `94cec8c38b375f77c053acf5202c5d46b7ee3e6aa493b15b16b954dcbcef45aa`.
- Ad-hoc signature verified; **not Developer ID signed or notarized**.
  [Installation/Gatekeeper instructions](MACOS_INSTALL.md).

## Executed checks

| Check | Result and scope |
| --- | --- |
| Windows regression suite | **251 passed**, including Playwright dashboard tests; Python 3.12.14 |
| Apple Silicon source suite | **251 passed, 0 skipped, 0 failures, 0 errors**, including the existing full review/test-generation/publishing UI tests with fake services |
| Packaging | PyInstaller created the standalone arm64 app with Python, Cocoa/WKWebView, Keychain backend, assets and the existing branded icon |
| Architecture and integrity | `lipo` arm64 check and strict deep `codesign` verification passed |
| Packaged Keychain | Real disposable entry created, read and deleted using the bundled executable; no file credential fallback |
| Packaged native UI | Dashboard, new review, code reviewer, history, watched repositories, test lab and settings rendered in WKWebView; route and page heading checked |
| Reopen / Finder-style launch | Three launches per smoke run, including `open -n -W` through Launch Services |
| Persistence | Config and watched repo persisted; a synthetic completed review survived app launches. This is a storage test, not an AI-generated review |
| Closing | App exited and managed server port closed after each native smoke launch |
| DMG | Created, verified with `hdiutil`, mounted read-only, app copied outside checkout, signature reverified, all packaged smoke checks repeated |
| Browser fallback | Unit tests cover explicit browser mode and native initialization failure, including server cleanup; actual fault-induced macOS dialog UX remains manual |
| Providers / GitHub / sandbox safeguards | Existing mocked suite verifies GitHub auth/error handling, pagination, AI providers, free-only selection, review pipeline, test generation, consent, typed publishing confirmation and Docker isolation |
| Website | 5 selector tests, lint and production build passed locally and in GitHub CI |
| Website responsive UI | Browser checks at 390px and 1440px, both absent and verified Mac-release fixtures; exact per-OS URLs, disabled Mac state, no horizontal overflow or JS errors; screenshots inspected |

The reports in the artifact describe the repeated checks on the **DMG's copied app**.
The build step ran the same checks on the initial packaged app before creating the DMG.

## Remaining acceptance checks and limitations

These did **not** run and must not be presented as successful:

- A completely new macOS user account with an Internet-quarantined download,
  Gatekeeper prompts, drag-to-Applications by a person and a locked login Keychain.
  CI instead used fresh app data, a disposable unlocked Keychain, a copied DMG app
  and Launch Services. No security protection was disabled.
- Physical M2, M3 and M4 machines, and macOS 14. The binary targets arm64/macOS 14+;
  execution was verified on GitHub's macOS 15 Apple Silicon runner.
- Live user GitHub OAuth/PAT authentication, private repos, PR retrieval, remote
  publication, real free OpenRouter inference, installed Ollama model inference,
  or a real Docker Desktop container run on macOS. Credentials/models/services
  were not supplied; fake-service tests do not replace these acceptance checks.
- A fault-induced native-window failure and browser Quit dialog usability on a
  person's Mac, downloaded-app Keychain access prompts across ad-hoc rebuilds,
  and an exhaustive system process audit. App exit and dashboard-server shutdown
  were explicitly verified in CI.

No Ollama models or Docker runtime are bundled. No paid APIs, Apple account,
Developer ID certificate or notarization service were required to build/test.

## Windows and release protection

`build_exe.ps1`, `requirements.txt`, Windows DPAPI implementation, Windows native
launch flow, `.github/workflows/release.yml`, its source branch default, CLI,
review pipelines/providers and publishing code remain unchanged. No Windows
workflow ran during this task.

All three pre-existing releases and their assets were rechecked after the build.
Windows `v0.1.2beta` still has the same release ID `399317292`, EXE/checksum names
and digests. The EXE SHA-256 remains:
`47867d2af0faa512798dab164ea76cd2b09a6af68609e3ff7ba53e7bb5dae6bf`.

The website retains that real Windows fallback. Mac downloads remain disabled
until an approved, verified Mac release exists. Proposed tag:
`macos-v0.1.3-beta.1`, pointing to the tested source SHA above. Its `macos-` prefix
avoids the existing Windows `v*` build trigger. Publication and website deployment
both still require owner approval. See [release strategy](MACOS_ENGINEERING.md)
and [zeropulsedev.com handoff](WEBSITE_DOWNLOAD_HANDOFF.md).
