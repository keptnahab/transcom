import { defineConfig } from 'vite'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const rendererRoot = dirname(fileURLToPath(import.meta.url))
const webPort = process.env.TRANSCOM_WEB_PORT || '8081'

export default defineConfig({
  root: rendererRoot,
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5747,
    strictPort: false,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${webPort}`,
        changeOrigin: true,
      },
    },
  },
})
