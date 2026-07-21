import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  cacheDir: 'C:/tmp/tax-accounting-platform-vite',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000'
    }
  }
})
