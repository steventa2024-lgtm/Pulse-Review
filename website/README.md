# PulseReview — website (by ZeroPulse)

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

The build uses a relative base (`./`), so `dist/` works on any static host.

## Deploy (Vercel)

Live at **https://pulse-review.vercel.app**. The Vercel project imports this repository with **Root Directory** `website`;
`vercel.json` sets the build (`npm run build`) and output (`dist`). No environment variables or secrets are needed.
Every push to `main` redeploys the site.

## Download button

The site reads the newest release (pre-releases included) from the GitHub API and links its `.exe` directly. If the API
can't be reached it falls back to `FALLBACK_DOWNLOAD_URL` in `src/config.ts`.

## Screenshots

`public/screenshots/*.webp` are real captures of the running app with sample data.
