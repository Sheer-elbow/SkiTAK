import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // In dev, proxy API and Socket.IO calls to the running OTS server
      // (make dev exposes the Flask API on 8081)
      '/api': { target: 'http://localhost:8081', changeOrigin: true },
      '/Marti': { target: 'http://localhost:8081', changeOrigin: true },
      '/socket.io': { target: 'ws://localhost:8081', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
