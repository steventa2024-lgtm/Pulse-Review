import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Relative base so the built site works on GitHub Pages (/Pulse-Review/), a custom domain, or any static host.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
})
