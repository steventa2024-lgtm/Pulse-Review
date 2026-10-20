# macOS port audit, build and release review

## Baseline inspected

- Application: `claude/ecstatic-ramanujan-qz4m34`, commit
  `e22ee6d4a3b5271a43e795f4d9367df88d0b3b78` (also the `v0.1.2beta` tag).
- Public branch: `main`, commit `7293f3954e69e33bf9a4a68e2f737902eb539707`.
  Its history has no merge base with the application branch, so changes use
  separate PRs against their respective bases. Do not merge the entire app
  branch into main to update downloads.
- Read `main.py`, `requirements.txt`, all platform-sensitive code under `core/`
  and `dashboard/`, shared CLI/pipelines/providers/publisher, tests,
  `build_exe.ps1`, website selectors and `.github/workflows/release.yml`.
- Windows-specific pieces: DPAPI ctypes; WebView2 registry detection;
  pywebview dependency marker; APPDATA; winget/start Docker; subprocess flags;
  ICO and PowerShell packaging. Docker discovery already includes macOS.
- Existing review/core code is portable Python. No pipeline/provider/publisher
  rewrites are necessary. Windows `requirements.txt`, DPAPI implementation,
  WebView2 flow, build script and release workflow remain unchanged.

## Build

On native Apple Silicon macOS with arm64 Python **3.11** and Apple's free
command-line tools, run `bash build_mac.sh` from a clean application checkout.
The script rejects Intel/Rosetta and creates a clean `.venv-mac`, runs tests,
bundles Python and dependencies, converts the existing icon to ICNS, validates
arm64/signature, smoke-tests the packaged WKWebView twice, creates a compressed
DMG, checks it, computes SHA-256, then mounts/copies/tests the DMG's app again.
Existing `dist/PulseReview.exe` and `.venv` are independent. Move an earlier
Mac DMG aside before a second build. Build dependencies are recorded; do not
assume builds are bit-for-bit reproducible.

Outputs under `dist/mac/`: `PulseReview.app`, `PulseReview-macOS-arm64.dmg`,
`PulseReview-macOS-arm64.dmg.sha256`, `build-info.json`, `dependencies.txt`.
Reports under `build/mac/`: JUnit, packaged diagnostics and native page checks.
No Python, build tools, models or paid APIs are required by an end user.

The macOS launcher uses Cocoa/WKWebView on its main thread with the existing
NiceGUI dashboard in a spawned process. NiceGUI's Windows native launcher stays
intact. pywebview's docs recommend py2app for Mac; PyInstaller's supported
arm64 app bundling is used here to retain the project's packaging stack.
Native rendering is a hard CI check, not assumed from a successful bundle.
Initialization failures visibly offer local-browser operation and a Quit control.

## CI and release approval

`macos.yml` uses GitHub's standard **macos-15 arm64** runner. PRs targeting the
application branch test their exact head SHA. A manually dispatched run requires
a full 40-character application SHA; main's website-only commit fails validation.
The workflow uses read-only repository permissions and uploads CI artifacts only.
There is no release publication step and no Windows build job. It also exists
in the main-branch PR for future manual dispatch after that PR is approved.
GitHub documents standard public-repository arm64 macOS runners as free.

Proposed first Mac tag: **`macos-v0.1.3-beta.1`**, targeting the tested app commit,
with the embedded manifest's full SHA in release notes. This intentionally differs
from Windows `v0.1.2beta`. The `macos-` prefix avoids the existing Windows `v*`
tag trigger. Do not reuse an existing tag or asset. After explicit owner approval,
prepare a separate prerelease containing only the verified DMG/checksum and
provenance. Never upload to the Windows release, clobber assets or move its tag.

After testing and owner publication approval, the Mac release notes must contain
these exact machine-readable lines (replace the SHA with the built source):

```text
PulseReview-Verified: macos-arm64
Source-Commit: <full 40-character application commit>
```

The website additionally requires a published Mac beta tag, exact DMG/checksum
names, nonempty assets and GitHub's SHA-256 asset digest. It independently selects
Windows and Mac by publication date, including prereleases, and retains the existing
Windows fallback URL during API failure. It never guesses a Mac URL.

Review-branch Vercel automatic deployments are explicitly disabled in
`website/vercel.json`; no deployment command is used. Merging the website PR
into main can deploy through the existing integration, so that merge itself
must wait for the owner's deployment approval.

## References

- https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support
- https://pywebview.flowrl.com/guide/freezing.html
- https://support.apple.com/en-us/102445
- https://vercel.com/docs/project-configuration/git-configuration
