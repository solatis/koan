import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  root: 'review',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5273,
    open: true,
    fs: {
      allow: ['..'],
    },
  },
})
