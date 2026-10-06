/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In production Flask serves the build (dist/) and the API from one origin.
// With `npm run dev`, Vite serves the app and proxies the API to the Flask
// dev server that `make dev` starts on port 8000.
export default defineConfig({
  plugins: [react()],
  build: {
    // React and Recharts in one chunk: 586 kB minified, 175 kB gzipped
    // (`npm run build`). Splitting it would not shrink a single-page app.
    chunkSizeWarningLimit: 700,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
