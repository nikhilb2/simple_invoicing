import posthog from 'posthog-js';

/**
 * PostHog product analytics.
 *
 * Everything funnels through this module rather than importing `posthog-js`
 * at each call site, for one reason: analytics is optional infrastructure. An
 * instance running with no PostHog project configured — a self-hosted copy, a
 * CI build, a contributor's checkout — must boot and behave identically, so
 * every export here is a no-op until `initAnalytics` has succeeded.
 *
 * Absent configuration is a supported state, not a fault: no warning, no
 * console noise, in any environment. Running without analytics is a choice the
 * operator is allowed to make quietly.
 */

let ready = false;

/**
 * Boots the PostHog client. Safe to call more than once; only the first call
 * with a complete configuration does anything. Returns without a sound when
 * either variable is unset.
 */
export function initAnalytics() {
  if (ready) {
    return;
  }

  const token = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN;
  const host = import.meta.env.VITE_POSTHOG_HOST;

  if (!token || !host) {
    return;
  }

  posthog.init(token, {
    api_host: host,
    // Pins the SDK's behaviour to a dated preset, so a future posthog-js
    // release cannot change what is autocaptured underneath us. This preset
    // captures pageviews on history changes, which is what an SPA router needs.
    defaults: '2026-05-30',
    disable_session_recording: false,
    session_recording: {
      // Every screen here is a private company's ledger, and all seven tenants
      // report into one PostHog project — so anything typed into an invoice,
      // ledger or company form is masked before it leaves the browser.
      maskAllInputs: true,
      // Rendered text is NOT masked by default: customer names, GSTINs and
      // invoice totals sitting in a table are recorded as they appear. Tag an
      // element with data-private to blank it out of the replay.
      maskTextSelector: '[data-private]',
    },
  });

  ready = true;
}

/** True once PostHog is configured and initialised. */
export function isAnalyticsReady() {
  return ready;
}

/**
 * Records a product event.
 *
 * Property values are deliberately limited to counts, ids, enums and money
 * totals — never customer names, addresses, item descriptions or anything else
 * off a document. Aggregate shape is what the funnels need; the contents of a
 * tenant's invoices are not ours to ship off-site.
 */
export function track(event: string, properties?: Record<string, unknown>) {
  if (!ready) {
    return;
  }

  posthog.capture(event, properties);
}

/**
 * Binds subsequent events to a known operator. Called on login, where the
 * email is the stable identifier the backend already keys accounts by.
 */
export function identifyUser(distinctId: string, properties?: Record<string, unknown>) {
  if (!ready) {
    return;
  }

  posthog.identify(distinctId, properties);
}

/**
 * Updates properties on the currently identified person. Used once the role
 * and active company arrive from /auth/me, a round-trip after login.
 */
export function setUserProperties(properties: Record<string, unknown>) {
  if (!ready) {
    return;
  }

  posthog.setPersonProperties(properties);
}

/**
 * Detaches the current operator so a shared machine's next sign-in starts a
 * fresh anonymous identity instead of inheriting the previous one's events.
 */
export function resetAnalyticsUser() {
  if (!ready) {
    return;
  }

  posthog.reset();
}

/** Reports a caught exception to PostHog error tracking. */
export function trackException(error: unknown, properties?: Record<string, unknown>) {
  if (!ready) {
    return;
  }

  posthog.captureException(error, properties);
}

export { posthog };
