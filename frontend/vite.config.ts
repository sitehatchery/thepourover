import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const apiTarget = process.env.CDP_API_URL ?? 'http://127.0.0.1:8000'

// In development the Vite server forwards API calls to FastAPI, mirroring the Apache/Nginx proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    // Trailing slashes matter: page routes like /app-events must stay with the React app. The Host header is
    // kept so links the API builds (e.g. the admin console's redirects) point back at this dev server.
    proxy: {
      '/app/': { target: apiTarget, changeOrigin: false },
      '/webhooks/': { target: apiTarget, changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    css: false,
  },
})
