/**
 * The web half of the bridge to the Simple Invoicing mobile app.
 *
 * The mobile app signs in natively and renders this web app inside a
 * react-native-webview, writing `token` and `refresh_token` into localStorage
 * before the page's scripts run -- so the store below starts signed in. The app
 * keeps its own copy of that pair in secure storage, which means it has to hear
 * about every change to it: a rotation on refresh, and a sign-out, whether the
 * user asked for it or a refresh failed underneath them.
 *
 * Outside the app none of this does anything; a browser has no
 * `window.ReactNativeWebView` and every message is dropped.
 *
 * The message union is a contract shared with the app. Keep it in sync with
 * `simple-invoicing-mobile/src/lib/bridge.ts`. The web side only ever sends
 * `logout` and `tokens` -- the app intercepts blob downloads itself through
 * injected JS -- but `download` stays here so the two copies read the same.
 */

export type NativeBridgeMessage =
  | { type: 'logout' }
  | { type: 'tokens'; accessToken: string; refreshToken: string }
  | { type: 'download'; filename: string; mimeType: string; base64: string };

declare global {
  interface Window {
    /** Injected by react-native-webview when running inside the mobile app. */
    ReactNativeWebView?: { postMessage(data: string): void };
  }
}

/** True when this page is running inside the mobile app's WebView. */
export function isNativeApp(): boolean {
  return typeof window !== 'undefined' && typeof window.ReactNativeWebView?.postMessage === 'function';
}

/**
 * Sends a message to the mobile app. A no-op in a browser, and never throws: a
 * bridge failure must not break the sign-in or sign-out that triggered it.
 */
export function postToNative(msg: NativeBridgeMessage) {
  if (!isNativeApp()) {
    return;
  }

  try {
    window.ReactNativeWebView!.postMessage(JSON.stringify(msg));
  } catch {
    // The app not listening is not the web app's problem to surface.
  }
}
