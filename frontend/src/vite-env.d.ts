/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** PostHog project token. Absent on instances that run without analytics. */
  readonly VITE_POSTHOG_PROJECT_TOKEN?: string;
  /** PostHog ingestion host, e.g. https://eu.i.posthog.com */
  readonly VITE_POSTHOG_HOST?: string;
}
