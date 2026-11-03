import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // Build into the Python package so the wheel ships a working UI.
    // `pip install llmwikify` then has `serve --web` serve real files
    // instead of 404ing (see llmwikify.interfaces.server.utils.webui).
    outDir: '../../src/llmwikify/webui/dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8765',
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
