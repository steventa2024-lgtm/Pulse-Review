## PulseReview — v0.1.2 beta

Beta of the Windows desktop app. **Beta software:** expect rough edges and please report issues.

### Download
- `PulseReview.exe` — single-file Windows 10/11 (x64) executable, no Python needed.
- `PulseReview.exe.sha256` — checksum.

The exe is not code-signed yet, so Windows SmartScreen may warn on first launch (More info → Run anyway).
It opens in a native window when the Microsoft Edge WebView2 runtime is present, otherwise in your default browser.

### New in 0.1.2
- The app is now called **PulseReview**, developed and licensed by **ZeroPulse** (see LICENSE). The download is now `PulseReview.exe`.
- Website: https://pulse-review.vercel.app
- Your settings, history and saved keys from earlier betas are kept (same data folder).

### New in 0.1.1
- Bring your own setup: review **public pull requests without signing in to GitHub** — just pick a model and paste the link
- Works fully offline-from-the-cloud with **Ollama** (no API keys at all)
- First-run "Get started" checklist on the dashboard and a one-click link to create a GitHub token
- Security audit of the repository: no API keys, tokens or OAuth client IDs are included in the source or the exe; every user adds their own

### What's included
- AI pull-request reviews with findings verified against the real diff, risk rating and suggested fixes
- One generated test file per review; optional isolated Docker sandbox to run it
- Code reviewer: audit a whole repository, a folder or a file (security, leaked secrets, bugs, performance, maintainability) with a scored breakdown
- Free OpenRouter models (API key required) or local models through Ollama
- Sign in with GitHub (device flow) or a personal access token; repository and PR pickers
- Human-in-the-loop publishing (COMMENT reviews only, stale/duplicate protection), review history, watched repositories, Test lab

### Built by
GitHub Actions on `windows-latest` with `build_exe.ps1` (tests run before packaging; the exe is launch-tested before publishing).
