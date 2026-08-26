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
      // The MCP endpoint and the OAuth discovery documents must be reachable on
      // the same origin as the app, so a single tunnel (cloudflared/ngrok) at
      // :5173 is a complete connector surface for testing against real Claude or
      // ChatGPT. In production the k8s ingress routes these same two prefixes.
      // '^/mcp' has no trailing slash on purpose: bare POST /mcp is the endpoint.
      '^/mcp': {
        target: process.env.API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
      '^/\\.well-known/': {
        target: process.env.API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    watch: {
      usePolling: true,
    },
  },
});
