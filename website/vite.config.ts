import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Relative base so the built site works on GitHub Pages (/Pulse-Review/), a custom domain, or any static host.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  // Tailwind v4 runs through its Vite plugin. An inline (empty) PostCSS config stops Vite from picking up a
  // postcss.config.* from a parent folder (e.g. an old Tailwind v3 setup in the user's home directory).
  css: { postcss: { plugins: [] } },
})
