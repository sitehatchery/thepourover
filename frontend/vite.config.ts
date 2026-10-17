import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiTarget = process.env.CDP_API_URL ?? 'http://127.0.0.1:8000'

// In development the Vite server forwards API calls to FastAPI, mirroring the Apache/Nginx proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    // Trailing slashes matter: page routes like /app-events must stay with the React app.
    proxy: {
      '/app/': apiTarget,
      '/webhooks/': apiTarget,
    },
  },
})
