# PulseReview website downloads — release handoff

This document covers the **PulseReview product website** in `website/`. It is separate from the ZeroPulse corporate site at `zeropulsedev.com`; no corporate-site edits are implied.

## Published releases

**Windows v0.1.2beta (unchanged)**

- EXE: https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/v0.1.2beta/PulseReview.exe
- Checksum: https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/v0.1.2beta/PulseReview.exe.sha256

**macOS Apple Silicon v0.1.3 Beta 1 — public prerelease**

- Release: https://github.com/steventa2024-lgtm/Pulse-Review/releases/tag/macos-v0.1.3-beta.1
- DMG: https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/macos-v0.1.3-beta.1/PulseReview-macOS-arm64.dmg
- Checksum: https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/macos-v0.1.3-beta.1/PulseReview-macOS-arm64.dmg.sha256
- Source commit: `68726a73d19f2b76a84193c49efa30b74c6d1e0f`
- DMG SHA-256: `94cec8c38b375f77c053acf5202c5d46b7ee3e6aa493b15b16b954dcbcef45aa`

The Mac release has the `PulseReview-Verified: macos-arm64` and `Source-Commit` release-notes markers, an asset checksum and a GitHub digest. The first approved Mac beta is now published; **the former “Mac coming soon” state is obsolete**.

## Website integration

The `Hero` and `Download` sections provide separate **Download for Windows** and **Download for macOS** controls.

`website/src/hooks/releaseSelection.ts` selects each platform independently and requires:
- A published release, not a draft.
- The exact platform asset name and checksum asset.
- For Mac, `macos-vX.Y.Z-beta.N` tag, GitHub SHA-256 digest and verification/source-commit markers.

Never use `/releases/latest` as a shared download link; the operating systems have different release tags. During a GitHub API outage, Windows retains its verified fallback, while the Mac control conservatively remains unavailable until release metadata can be checked. The presence of markers is a maintainer attestation, **not** a browser-side cryptographic verification of downloaded bytes.

Installation, Gatekeeper warnings and beta testing limits are documented in the root README, `docs/MACOS_INSTALL.md`, and the GitHub release.

## Deployment and scope

The review branches intentionally disable preview deployments. Merge the website changes into `main` only when approved for PulseReview website deployment. The existing Vercel integration may automatically deploy `main`, so validate the live website afterwards.

Do not merge the separate macOS application PR #2 merely to publish the website. Application branch history diverges from the website's `main` history and must be reconciled separately.

No changes to the corporate `zeropulsedev.com` website are included.
