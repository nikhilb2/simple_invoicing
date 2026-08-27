import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// Resolved once per build. BUILD_VERSION is an escape hatch so a CI job can pin a
// git sha instead of a timestamp; any value works as long as a new build produces
// a new one.
const BUILD_VERSION = process.env.BUILD_VERSION || new Date().toISOString();

/**
 * Stamps the build version in two places from one source: `version.json` beside
 * the bundle, and `__BUILD_VERSION__` inside it. A tab compares the two and
 * offers a reload when they diverge — without which a browser holding the
 * `immutable`-cached assets of an old image never learns a new one shipped.
 *
 * This lives in the Vite config rather than the Dockerfile so that every build
 * path gets it: docker, kaniko, the per-tenant build-and-push scripts, CI, and a
 * plain `npm run build`.
 */
function buildVersionPlugin(): Plugin {
  const body = `${JSON.stringify({ version: BUILD_VERSION })}\n`;

  return {
    name: 'build-version',
    // There is no bundle to emit into under `npm run dev`, so serve the same
    // body from memory. Otherwise the poller 404s on every tick in dev and the
    // feature can only be exercised against a built image.
    configureServer(server) {
      server.middlewares.use('/version.json', (_req, res) => {
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Cache-Control', 'no-cache');
        res.end(body);
      });
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'version.json', source: body });
    },
  };
}

export default defineConfig({
  plugins: [react(), buildVersionPlugin()],
  define: {
    __BUILD_VERSION__: JSON.stringify(BUILD_VERSION),
  },
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
