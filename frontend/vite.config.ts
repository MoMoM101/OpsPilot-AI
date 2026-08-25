import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
  plugins: [react()],
  cacheDir: '.cache/vite',
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  preview: { host: '127.0.0.1', port: 4174 },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  }
})
