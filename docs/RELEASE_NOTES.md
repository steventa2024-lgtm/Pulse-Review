## ZeroPulse PR Review Agent — v0.1.0 beta

First public beta of the Windows desktop app. **Beta software:** expect rough edges and please report issues.

### Download
- `ZeroPulsePRReview.exe` — single-file Windows 10/11 (x64) executable, no Python needed.
- `ZeroPulsePRReview.exe.sha256` — checksum.

The exe is not code-signed yet, so Windows SmartScreen may warn on first launch (More info → Run anyway).
It opens in a native window when the Microsoft Edge WebView2 runtime is present, otherwise in your default browser.

### What's included
- AI pull-request reviews with findings verified against the real diff, risk rating and suggested fixes
- One generated test file per review; optional isolated Docker sandbox to run it
- Code reviewer: audit a whole repository, a folder or a file (security, leaked secrets, bugs, performance, maintainability) with a scored breakdown
- Free OpenRouter models (API key required) or local models through Ollama
- Sign in with GitHub (device flow) or a personal access token; repository and PR pickers
- Human-in-the-loop publishing (COMMENT reviews only, stale/duplicate protection), review history, watched repositories, Test lab

### Built by
GitHub Actions on `windows-latest` with `build_exe.ps1` (tests run before packaging; the exe is launch-tested before publishing).
