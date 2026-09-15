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

  it('posts logout once when the refresh fails, however many requests were waiting', async () => {
    vi.spyOn(axios, 'post').mockRejectedValue(new Error('refresh rejected'));

    const results = await Promise.allSettled([api.get('/a'), api.get('/b')]);

    expect(results.map((r) => r.status)).toEqual(['rejected', 'rejected']);
    expect(store).toEqual({});
    expect(sentMessages()).toEqual([{ type: 'logout' }]);
  });

  it('does not post again for a 401 once the session is already gone', async () => {
    store = {};
    const refresh = vi.spyOn(axios, 'post');

    await expect(api.get('/anything')).rejects.toBeInstanceOf(AxiosError);

    expect(refresh).not.toHaveBeenCalled();
    expect(postMessage).not.toHaveBeenCalled();
  });
});
