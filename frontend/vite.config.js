import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        // local dev -> http://localhost:8000 ; docker-compose sets
        // VITE_API_PROXY=http://api:8000 (compose service name)
        target: process.env.VITE_API_PROXY || 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})