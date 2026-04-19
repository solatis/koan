import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  // In production the built assets live at /static/app/ on the Python server.
  // This must match the StaticFiles mount path in create_app().
  base: '/static/app/',

  build: {
    // Output directly into the Python package's static directory so
    // `uv run koan` serves the latest build without a copy step.
    outDir: '../koan/web/static/app',
    emptyOutDir: true,

    // Dev-friendly build: keep readable names and source maps so React
    // DevTools, browser debugger, and console traces are useful.
    // The bundle is only served locally — size doesn't matter.
    sourcemap: true,
    minify: false,
  },

  server: {
    proxy: {
      // Proxy all backend traffic through Vite's dev server.
      // The SSE endpoint (/events) needs special handling: disable buffering
      // so chunks are forwarded immediately rather than batched. Without this,
      // SSE events arrive in groups after a delay, breaking the real-time feed.
      '/events': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Accept', 'text/event-stream')
          })
          proxy.on('proxyRes', (proxyRes) => {
            // Prevent any intermediate buffering (nginx, proxies, etc.)
            proxyRes.headers['x-accel-buffering'] = 'no'
            proxyRes.headers['cache-control'] = 'no-cache'
          })
        },
      },
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/mcp': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
