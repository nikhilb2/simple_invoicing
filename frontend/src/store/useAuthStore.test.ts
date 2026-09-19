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
});
