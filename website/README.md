# ZeroPulse PR Review Agent — showcase website

Single-page product site for the desktop app. React + TypeScript + Vite + Tailwind CSS v4 + Lucide icons.
It is a separate layer: nothing here changes the desktop application.

## Develop

```bash
cd website
npm install
npm run dev        # http://localhost:5173
```

## Build & check

```bash
npm run lint       # oxlint
npm run build      # tsc -b && vite build  → website/dist
npm run preview    # serve the production build on http://localhost:4173
```

The build uses a relative base (`./`), so `dist/` can be hosted at a domain root, under `/Pulse-Review/` on GitHub Pages,
or on any static host (Netlify, Vercel, Cloudflare Pages, S3…).

## Deploy (GitHub Pages)

`.github/workflows/website.yml` builds and deploys on every push that touches `website/`.
One-time setup: **Repository → Settings → Pages → Build and deployment → Source: GitHub Actions**.
The site is then served at `https://steventa2024-lgtm.github.io/Pulse-Review/`
(update the `og:image` URLs in `index.html` if you use a custom domain).

## Download button

`src/hooks/useRelease.ts` reads the newest published GitHub release (pre-releases included) from the GitHub API and links to
its `.exe` asset, showing the real version, size and date. If the API is unreachable it falls back to the
`FALLBACK_DOWNLOAD_URL` in `src/config.ts` (currently the `v0.1.1beta` asset). New releases are picked up automatically —
publish them with `.github/workflows/release.yml`.

## Screenshots

`public/screenshots/*.webp` are real captures of the running app (sample data, 2× resolution):

```bash
# from the repo root, with the app's Python environment + playwright + Pillow
mkdir -p /tmp/zp-demo && cd /tmp/zp-demo
ZEROPULSE_DATA_DIR=/tmp/zp-demo python <repo>/website/scripts/demo_app.py 8790 &
python <repo>/website/scripts/capture_screenshots.py http://127.0.0.1:8790
```

`demo_app.py` runs the real dashboard code; only GitHub and the model are replaced by offline sample data.
You can also replace any file with your own screenshot of the same name.

## Deploy to Vercel

Vercel → **Add New… → Project** → import `steventa2024-lgtm/Pulse-Review` → set **Root Directory** to `website` → **Deploy**.
`website/vercel.json` already sets the build (`npm run build`) and output (`dist`). No environment variables or secrets are needed.
