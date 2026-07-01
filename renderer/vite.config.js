import { defineConfig } from 'vite'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const rendererRoot = dirname(fileURLToPath(import.meta.url))

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
  },
})
