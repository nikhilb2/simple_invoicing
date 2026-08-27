/// <reference types="vite/client" />

/** Build stamp injected by the `build-version` plugin in vite.config.ts. */
declare const __BUILD_VERSION__: string;

interface ImportMetaEnv {
  /** PostHog project token. Absent on instances that run without analytics. */
  readonly VITE_POSTHOG_PROJECT_TOKEN?: string;
  /** PostHog ingestion host, e.g. https://eu.i.posthog.com */
  readonly VITE_POSTHOG_HOST?: string;
}
