# Website download handoff — zeropulsedev.com

No changes have been made to zeropulsedev.com. Access and explicit deployment
approval are required before editing it.

Current real Windows download (unchanged):
https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/v0.1.2beta/PulseReview.exe

Current real Windows checksum:
https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/v0.1.2beta/PulseReview.exe.sha256

There is no published Mac release yet. Do not add a live Mac download link until
the owner approves publication and the assets are verified. Planned first tag:
macos-v0.1.3-beta.1, built from the exact tested application commit.

Future URL template — not currently a working download:
https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/<APPROVED_MAC_TAG>/PulseReview-macOS-arm64.dmg

Future checksum template:
https://github.com/steventa2024-lgtm/Pulse-Review/releases/download/<APPROVED_MAC_TAG>/PulseReview-macOS-arm64.dmg.sha256

Reuse website/src/hooks/releaseSelection.ts for independent per-OS selection.
It requires the exact file name, checksum asset, GitHub SHA-256 digest, published
Mac tag and maintainer verification/source-commit lines. Never use /releases/latest
for both platforms: a Mac-only prerelease and the Windows release have independent
versions. An API error must retain the known Windows URL and leave Mac unavailable.

The verification marker records a maintainer's acceptance; the website does not
cryptographically validate the full DMG during page load. Users can verify the
published checksum. Do not add the marker until the app and installer passed
acceptance and the owner approved the release.

Review branches explicitly disable Vercel automatic deployments. Do not merge
the website PR into main until deployment is approved: the existing main branch
integration may deploy immediately on merge.
