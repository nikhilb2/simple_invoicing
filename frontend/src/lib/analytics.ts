import posthog from 'posthog-js';

/**
 * PostHog session replay.
 *
 * This module records sessions and nothing else. Product events are captured
 * server-side, in the FastAPI route handlers (see backend/src/core/analytics.py),
 * so an event fires when the write actually committed rather than when a request
 * merely appeared to succeed, and the same action performed through the MCP
 * connector or an API key is counted identically.
 *
 * What is left here is the replay and the identity it hangs off: `initAnalytics`
 * to start recording, `identifyUser` so a recording is attributable to the
 * operator the backend is already keying events by, and `resetAnalyticsUser` so a
 * shared machine does not inherit the previous sign-in.
 *
 * Absent configuration is a supported state, not a fault: with no PostHog project
 * configured -- a self-hosted copy, a CI build, a contributor's checkout -- every
 * export here is a no-op, with no warning and no console noise, in any
 * environment. Running without analytics is a choice the operator is allowed to
 * make quietly.
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
    // Autocapture and pageviews stay on. What moved to the backend is the named
    // product events -- invoice_created and friends -- because those must fire
    // when the write committed, not when a request appeared to succeed. The
    // ambient stream of clicks, form submits and pageviews is the browser's to
    // record, and it is what gives a replay its timeline.
    disable_session_recording: false,
    session_recording: {
      // Input text is recorded as typed, so a replay shows what was actually
      // entered into an invoice, ledger or company form. Every screen here is a
      // private company's ledger and all seven tenants report into one PostHog
      // project, so keep sensitive fields out of a replay one at a time: tag
      // the input with data-private (see maskTextSelector below), or give it
      // type="password", which posthog-js masks regardless of this setting.
      maskAllInputs: false,
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
 * The id of the recording in progress, for the API client to pass to the
 * backend on every request.
 *
 * This is the whole link between the two halves: PostHog stitches an event to a
 * replay by `$session_id`, so a server-side event only lands on the recording's
 * timeline if the browser tells the backend which session it belongs to.
 * Returns null when analytics is off or a session has not started yet.
 */
export function getSessionId(): string | null {
  if (!ready) {
    return null;
  }

  return posthog.get_session_id() || null;
}

/**
 * Binds the recording to a known operator. Called on login, where the email is
 * the stable identifier the backend already keys accounts by -- the two sides
 * must agree, or the replay and the events it produced land on two different
 * people.
 */
export function identifyUser(distinctId: string, properties?: Record<string, unknown>) {
  if (!ready) {
    return;
  }

  posthog.identify(distinctId, properties);
}

/**
 * Detaches the current operator so a shared machine's next sign-in starts a
 * fresh anonymous identity instead of inheriting the previous one's recordings.
 */
export function resetAnalyticsUser() {
  if (!ready) {
    return;
  }

  posthog.reset();
}

export { posthog };
