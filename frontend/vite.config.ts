import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendUrl = process.env.TAX_WORKBENCH_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  cacheDir: 'C:/tmp/tax-accounting-platform-vite',
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': backendUrl
    }
  }
})
