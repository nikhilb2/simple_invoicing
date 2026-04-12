import axios, { AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api';

const api = axios.create({
  baseURL,
  timeout: 10000,
});

let refreshPromise: Promise<string | null> | null = null;

type RetryableRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean;
};

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (!axios.isAxiosError(error)) {
      return Promise.reject(error);
    }

    const status = error.response?.status;
    const originalRequest = error.config as RetryableRequestConfig | undefined;
    const requestUrl = originalRequest?.url || '';
    const isRefreshCall = requestUrl.includes('/auth/refresh');

    if (status !== 401 || !originalRequest || originalRequest._retry || isRefreshCall) {
      return Promise.reject(error);
    }

    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) {
      localStorage.removeItem('token');
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    if (!refreshPromise) {
      refreshPromise = axios
        .post(`${baseURL}/auth/refresh`, { refresh_token: refreshToken })
        .then((res) => {
          const nextAccessToken = res.data?.access_token as string | undefined;
          const nextRefreshToken = res.data?.refresh_token as string | undefined;

          if (!nextAccessToken || !nextRefreshToken) {
            throw new Error('Invalid refresh response');
          }

          localStorage.setItem('token', nextAccessToken);
          localStorage.setItem('refresh_token', nextRefreshToken);
          return nextAccessToken;
        })
        .catch(() => {
          localStorage.removeItem('token');
          localStorage.removeItem('refresh_token');
          return null;
        })
        .finally(() => {
          refreshPromise = null;
        });
    }

    const newToken = await refreshPromise;
    if (!newToken) {
      return Promise.reject(error);
    }

    if (!originalRequest.headers) {
      originalRequest.headers = {} as InternalAxiosRequestConfig['headers'];
    }
    (originalRequest.headers as Record<string, string>).Authorization = `Bearer ${newToken}`;

    return api.request(originalRequest);
  }
);

export function getApiErrorMessage(error: unknown, fallback = 'Something went wrong') {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallback;
}

export function cleanParams(params: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => {
      if (value === undefined || value === null || value === '') {
        return false;
      }
      if (Array.isArray(value)) {
        return value.length > 0;
      }
      return true;
    })
  );
}

export function withParams<T>(config: AxiosRequestConfig<T>, params: Record<string, unknown>): AxiosRequestConfig<T> {
  return {
    ...config,
    params: cleanParams(params),
  };
}

export default api;
