import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import axios from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api from './client';

/* Node environment, no DOM: storage is an in-memory stub and the WebView bridge
   a stubbed window. The API's transport is replaced with an adapter that only
   accepts the refreshed token, and the refresh call itself (made on the bare
   axios instance) is spied on. */

let store: Record<string, string> = {};
const postMessage = vi.fn();

function sentMessages() {
  return postMessage.mock.calls.map(([data]) => JSON.parse(data as string));
}

function respond(config: InternalAxiosRequestConfig, status: number): AxiosResponse {
  return { data: {}, status, statusText: String(status), headers: {}, config };
}

/** What axios rejects the refresh call with when the server answers `status`. */
function refreshFailure(status: number) {
  const config = { headers: {} } as InternalAxiosRequestConfig;
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_RESPONSE', config, null, respond(config, status));
}

beforeEach(() => {
  store = { token: 'old-access', refresh_token: 'old-refresh' };
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => { store[key] = String(value); },
    removeItem: (key: string) => { delete store[key]; },
  });
  vi.stubGlobal('window', { ReactNativeWebView: { postMessage } });

  api.defaults.adapter = async (config) => {
    if (config.headers.Authorization === 'Bearer new-access') {
      return respond(config, 200);
    }
    throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, respond(config, 401));
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  postMessage.mockReset();
});

describe('refresh interceptor and the native bridge', () => {
  it('posts the rotated pair after a successful refresh', async () => {
    vi.spyOn(axios, 'post').mockResolvedValue({
      data: { access_token: 'new-access', refresh_token: 'new-refresh' },
    });

    await expect(api.get('/anything')).resolves.toMatchObject({ status: 200 });

    expect(store).toMatchObject({ token: 'new-access', refresh_token: 'new-refresh' });
    expect(sentMessages()).toEqual([
      { type: 'tokens', accessToken: 'new-access', refreshToken: 'new-refresh' },
    ]);
  });

  it.each([401, 403])(
    'posts logout once when the refresh token is rejected with %i, however many requests were waiting',
    async (status) => {
      vi.spyOn(axios, 'post').mockRejectedValue(refreshFailure(status));

      const results = await Promise.allSettled([api.get('/a'), api.get('/b')]);

      expect(results.map((r) => r.status)).toEqual(['rejected', 'rejected']);
      expect(store).toEqual({});
      expect(sentMessages()).toEqual([{ type: 'logout' }]);
    },
  );

  it.each([
    ['a network error', new AxiosError('Network Error', AxiosError.ERR_NETWORK)],
    ['a timeout', new AxiosError('timeout exceeded', AxiosError.ECONNABORTED)],
    ['a 500', refreshFailure(500)],
    ['a 503', refreshFailure(503)],
  ])('clears the tokens but does not post logout when the refresh fails with %s', async (_, failure) => {
    vi.spyOn(axios, 'post').mockRejectedValue(failure);

    await expect(api.get('/anything')).rejects.toBeInstanceOf(AxiosError);

    // Web behaviour is unchanged; the app keeps its pair and re-injects it.
    expect(store).toEqual({});
    expect(postMessage).not.toHaveBeenCalled();
  });

  it('does not post again for a 401 once the session is already gone', async () => {
    store = {};
    const refresh = vi.spyOn(axios, 'post');

    await expect(api.get('/anything')).rejects.toBeInstanceOf(AxiosError);

    expect(refresh).not.toHaveBeenCalled();
    expect(postMessage).not.toHaveBeenCalled();
  });
});
