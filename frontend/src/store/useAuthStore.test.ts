import type { AxiosResponse } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api/client';
import { useAuthStore } from './useAuthStore';

/* The store reads localStorage the moment its module loads, so the in-memory
   stub has to be in place before the imports above run. */
const store = vi.hoisted(() => {
  const data: Record<string, string> = {};
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => (key in data ? data[key] : null),
      setItem: (key: string, value: string) => { data[key] = String(value); },
      removeItem: (key: string) => { delete data[key]; },
    },
  });
  return data;
});

const postMessage = vi.fn();

function sentMessages() {
  return postMessage.mock.calls.map(([data]) => JSON.parse(data as string));
}

beforeEach(() => {
  vi.stubGlobal('window', { ReactNativeWebView: { postMessage } });
  api.defaults.adapter = async (config): Promise<AxiosResponse> => {
    const data = config.url === '/auth/login'
      ? { access_token: 'access', refresh_token: 'refresh' }
      : { role: 'admin', active_company_id: null };
    return { data, status: 200, statusText: 'OK', headers: {}, config };
  };
});

afterEach(() => {
  vi.unstubAllGlobals();
  postMessage.mockReset();
  for (const key of Object.keys(store)) {
    delete store[key];
  }
});

describe('auth store and the native bridge', () => {
  it('posts the new pair on login', async () => {
    await useAuthStore.getState().login('a@example.com', 'secret');

    expect(store).toMatchObject({ token: 'access', refresh_token: 'refresh' });
    expect(sentMessages()).toEqual([{ type: 'tokens', accessToken: 'access', refreshToken: 'refresh' }]);
  });

  it('posts logout once storage is cleared', () => {
    store.token = 'access';
    store.refresh_token = 'refresh';
    // Snapshotted rather than asserted inside the mock: postToNative swallows
    // anything postMessage throws, a failed expect included.
    let storageWhenPosted: Record<string, string> | null = null;
    postMessage.mockImplementation(() => {
      storageWhenPosted = { ...store };
    });

    useAuthStore.getState().logout();

    expect(sentMessages()).toEqual([{ type: 'logout' }]);
    expect(storageWhenPosted).toEqual({});
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('setSession stores the pair, tells the native bridge and records the active company', async () => {
    api.defaults.adapter = async (config): Promise<AxiosResponse> => ({
      data: { role: 'staff', active_company_id: 7 },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    });

    await useAuthStore.getState().setSession({ access_token: 'a2', refresh_token: 'r2', token_type: 'bearer' });

    expect(store).toMatchObject({ token: 'a2', refresh_token: 'r2', active_company_id: '7' });
    expect(sentMessages()).toEqual([{ type: 'tokens', accessToken: 'a2', refreshToken: 'r2' }]);
    expect(useAuthStore.getState()).toMatchObject({ token: 'a2', userRole: 'staff' });
  });

  it('setSession clears a stale active company when the user has none', async () => {
    store.active_company_id = '99';

    await useAuthStore.getState().setSession({ access_token: 'a3', refresh_token: 'r3', token_type: 'bearer' });

    expect(store.active_company_id).toBeUndefined();
  });
});
