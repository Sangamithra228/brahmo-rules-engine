import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies the API so the frontend can be developed on :5173
// while FastAPI runs on :8000, with no CORS juggling and no hardcoded host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ['/health', '/users', '/hierarchy', '/pipeline', '/admin'].map((p) => [
        p,
        { target: 'http://localhost:8000', changeOrigin: true },
      ])
    ),
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
