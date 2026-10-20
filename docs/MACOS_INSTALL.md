# PulseReview by ZeroPulse — Apple Silicon macOS beta

Requires an Apple Silicon Mac (M1, M2, M3, M4) running macOS 14 or later.
Intel Macs and macOS 13 or older are not supported by this build. Python,
Xcode and command-line development tools are not required to use the app.

1. Download `PulseReview-macOS-arm64.dmg` and its `.sha256` from the approved
   **Mac beta** release. Windows EXEs are separate downloads.
2. Optionally verify the checksum in Terminal with
   `shasum -a 256 -c PulseReview-macOS-arm64.dmg.sha256` in the download folder.
3. Open the DMG in Finder and drag **PulseReview.app** to **Applications**.
   Eject the disk image, then open PulseReview from Applications.

## Gatekeeper and signing

This free beta uses an ad-hoc code signature. It is **not Developer ID signed
or notarized**. Apple cannot verify ZeroPulse's identity or that Apple has
checked it for malware; a download may be blocked or show warnings.

If you trust the verified download, try opening it once, then open **System
Settings → Privacy & Security**, find PulseReview under Security and choose
**Open Anyway**, if macOS offers that option. Confirm the app-specific prompt.
Managed Macs may prohibit exceptions. If macOS reports malware or a damaged
app, stop and obtain a fresh verified build; do not bypass that alert.
Do not disable Gatekeeper, SIP or system-wide protections, or remove quarantine
attributes to circumvent checks. See [Apple's current instructions](https://support.apple.com/en-us/102445).

Developer ID distribution and notarization normally require paid Apple Developer
Program membership. Building, testing and packaging this beta do not.

## Settings, history and credentials

Settings, watched repositories, SQLite review history, logs and generated
artifacts persist in `~/Library/Application Support/ZeroPulse/PulseReview/`.
Upgrading or moving the app does not remove them. GitHub access/refresh tokens
and OpenRouter API keys use the **macOS login Keychain**, service
`com.zeropulse.PulseReview`. Allow PulseReview access when macOS prompts.
Unlock your login keychain if access fails. A denied/locked Keychain does not
cause credentials to be saved to a file. Rebuilt ad-hoc apps may prompt again.

The old development-only Base64 files are not imported. Re-enter credentials
in Settings, revoke any previously exposed credentials and remove old files
after verifying the new Keychain entries. `ZEROPULSE_DATA_DIR` changes the data
directory for tests/development; it never bypasses Keychain.

## Using PulseReview

The same dashboard, PR reviews, code audits, watched repos, history, settings,
test generation and manual publishing confirmation are retained. GitHub sign-in
uses the existing configured OAuth client ID; a personal access token remains
available. Public repository reviews can run without GitHub sign-in.

OpenRouter uses only models currently verified free by the existing provider;
free account/rate limits still apply. Ollama is optional, connects to the same
localhost endpoint, and requires your own separately installed models. No models
are included in the DMG. Docker is optional: when unavailable, generated tests
remain explicitly unexecuted. Start installed Docker Desktop from Settings;
install it separately if needed. No PR code runs directly on your Mac.

Closing the native window stops its managed dashboard server. If WKWebView
cannot initialize, the same dashboard opens in the default local browser and a
**Browser Mode** dialog provides **Quit** to stop the server. Keep the dialog
open while working; closing a browser tab alone does not stop the app.
For troubleshooting, launching the executable with `--browser` forces that
mode. Logs are in the data directory's `logs/app.log`.
