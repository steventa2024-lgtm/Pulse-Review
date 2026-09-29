<p align="center">
  <img src="website/public/brand/banner.jpg" alt="PulseReview — Automated PR Review Agent, developed and licensed by ZeroPulse" width="100%">
</p>

<p align="center">
  <img src="website/public/brand/icon.png" alt="PulseReview app icon" width="96"><br>
  <b>AI pull-request reviews on your desktop · free open-weight models · you approve everything that gets posted</b>
</p>

<p align="center">
  <a href="https://pulse-review-three.vercel.app/"><b>🌐 Website</b></a> ·
  <a href="https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/v0.1.2beta/PulseReview.exe"><b>⬇ Download for Windows (v0.1.2 beta)</b></a> ·
  <a href="https://github.com/steventa2024-lgtm/Pulse-Review/releases">All downloads</a>
</p>

# PulseReview

PulseReview is a Windows desktop app that reviews GitHub pull requests with AI. Pick a pull request, choose a model,
and get findings checked against the real diff, a risk rating, suggested fixes and a proposed test file. Nothing is posted
to GitHub until you confirm it.

Developed and licensed by **ZeroPulse**.

## Downloads

| File | What it is |
| --- | --- |
| [`PulseReview.exe`](https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/v0.1.2beta/PulseReview.exe) | Single-file app for Windows 10/11 (64-bit). No install or Python needed. |
| [`PulseReview.exe.sha256`](https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/v0.1.2beta/PulseReview.exe.sha256) | Checksum, to verify the download. |

Older and newer builds are on the [Releases page](https://github.com/steventa2024-lgtm/Pulse-Review/releases).
The exe isn't code-signed yet, so Windows SmartScreen may warn the first time: **More info → Run anyway**.

## Getting started (beta testers)

1. Download and run `PulseReview.exe`.
2. **Pick an AI model** in **Settings → AI models**. Either option is free:
   * **Ollama (local, no account):** install [Ollama](https://ollama.com), then use **Get more models** in the app.
   * **OpenRouter:** paste your own free [OpenRouter](https://openrouter.ai) API key. Only free models are listed and used.
3. **Review a pull request:** **New review** → paste a public pull-request link → **Start review**.
4. *(Optional)* **Connect GitHub** in **Settings → GitHub** with a personal access token to review private repositories and publish comments.
5. *(Optional)* Install **Docker Desktop** to run the generated tests in an isolated sandbox.

Your code, API keys and tokens stay on your computer. Keys are encrypted with Windows' built-in protection, and nothing is sent to ZeroPulse.

## Features

* Pull-request reviews with findings verified against the diff, risk rating and suggested fixes
* One generated test file per review, with an optional isolated Docker sandbox to run it
* **Code reviewer:** audit a whole repository, a folder or one file for security issues, leaked keys, bugs, performance and maintainability, with a scored breakdown
* Free OpenRouter models or local Ollama models. Paid models are never used.
* You approve every GitHub post. Reviews are only ever posted as comments.
* Review history, watched repositories and a Test lab

## Feedback

Found a bug or have an idea? [Open an issue](https://github.com/steventa2024-lgtm/Pulse-Review/issues).

## Contributors

<a href="https://github.com/steventa2024-lgtm"><img src="https://github.com/steventa2024-lgtm.png" width="64" alt="steventa2024-lgtm"></a>

* **ZeroPulse** ([@steventa2024-lgtm](https://github.com/steventa2024-lgtm)): creator, developer and licensor

## License

PulseReview is proprietary beta software, © 2026 ZeroPulse. See [LICENSE](LICENSE).

## What's in this repository

* `website/`: source of [pulse-review.vercel.app](https://pulse-review.vercel.app)
* `.github/workflows/release.yml`: builds and publishes the Windows downloads
