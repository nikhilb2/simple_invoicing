import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Anchored with a trailing slash, not a bare '/api': the bare prefix also
      // claimed the app's own /api-keys route, so loading or refreshing that
      // page in dev returned the backend's {"detail":"Not Found"} JSON instead
      // of the page.
      '^/api/': {
        target: process.env.API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    watch: {
      usePolling: true,
    },
  },
});
