import { afterEach, describe, expect, it, vi } from 'vitest';
import { isNativeApp, postToNative } from './nativeBridge';

/* vitest runs in node here, so there is no window at all unless a test stubs
   one -- which is also the browser-without-the-app case worth covering. */

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('native bridge', () => {
  it('does nothing outside the app', () => {
    expect(isNativeApp()).toBe(false);
    expect(() => postToNative({ type: 'logout' })).not.toThrow();

    vi.stubGlobal('window', {});
    expect(isNativeApp()).toBe(false);
    expect(() => postToNative({ type: 'logout' })).not.toThrow();
  });

  it('posts the message as JSON inside the app', () => {
    const postMessage = vi.fn();
    vi.stubGlobal('window', { ReactNativeWebView: { postMessage } });

    expect(isNativeApp()).toBe(true);
    postToNative({ type: 'tokens', accessToken: 'a', refreshToken: 'r' });

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(JSON.parse(postMessage.mock.calls[0][0])).toEqual({
      type: 'tokens',
      accessToken: 'a',
      refreshToken: 'r',
    });
  });

  it('swallows a postMessage that throws', () => {
    vi.stubGlobal('window', {
      ReactNativeWebView: {
        postMessage: () => {
          throw new Error('bridge gone');
        },
      },
    });

    expect(() => postToNative({ type: 'logout' })).not.toThrow();
  });
});
