import axios, { AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';
import { getSessionId } from '../lib/analytics';
import { postToNative } from '../lib/nativeBridge';

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api';

/** The API root, for the few URLs the browser navigates to rather than fetches. */
export const apiBaseURL = baseURL;

const api = axios.create({
  baseURL,
  timeout: 10000,
});

let refreshPromise: Promise<string | null> | null = null;

type RetryableRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean;
  _companyRetry?: boolean;
};

/** The X-Company-Id value a failed request actually sent, if any. */
function readSentCompanyId(headers: unknown): string | undefined {
  if (!headers || typeof headers !== 'object') {
    return undefined;
  }
  const getter = (headers as { get?: unknown }).get;
  if (typeof getter === 'function') {
    const value = (getter as (name: string) => unknown).call(headers, 'X-Company-Id');
    return typeof value === 'string' ? value : undefined;
  }
  const value = (headers as Record<string, unknown>)['X-Company-Id'];
  return typeof value === 'string' ? value : undefined;
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  const activeCompanyId = localStorage.getItem('active_company_id');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  if (activeCompanyId) {
    config.headers['X-Company-Id'] = activeCompanyId;
  }
  // The link between the replay this browser is recording and the events the
  // backend captures for the request it is about to make. PostHog stitches the
  // two together by session id; without this header a server-side event lands on
  // the right person but on no recording's timeline. Absent when analytics is
  // not configured, and the backend treats it as advisory.
  const sessionId = getSessionId();
  if (sessionId) {
    config.headers['X-PostHog-Session-Id'] = sessionId;
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

    // A stored company id can go stale (e.g. a database restore while the
    // browser is still logged in). The server answers those company-scoped
    // requests 404 'Company not found' — including the startup company
    // query, which races hydrateUserRole's /auth/me correction — or 403
    // 'You do not have access to this company' when the id names a company
    // the user cannot reach. Rather than showing that error, drop the stale
    // id and retry once without it: the server then resolves the user's
    // first accessible company (or the company_required redirect when there
    // is none), and later requests stop sending the stale id because it is
    // no longer stored. Only reads are retried: resending a write without
    // its company header would apply it to whatever company the server
    // picks instead. And the stored id is only cleared when it is still the
    // one that failed, so a newer id (e.g. /auth/me's correction landing
    // while this request was in flight) is never wiped.
    const sentCompanyId = readSentCompanyId(originalRequest?.headers);
    const isStaleCompanyError =
      (status === 404 && error.response?.data?.detail === 'Company not found') ||
      (status === 403 && error.response?.data?.detail === 'You do not have access to this company');
    if (
      isStaleCompanyError &&
      originalRequest &&
      !originalRequest._companyRetry &&
      !requestUrl.includes('/auth/') &&
      sentCompanyId
    ) {
      originalRequest._companyRetry = true;
      if (localStorage.getItem('active_company_id') === sentCompanyId) {
        localStorage.removeItem('active_company_id');
      }
      const method = (originalRequest.method || 'get').toLowerCase();
      if (method !== 'get' && method !== 'head') {
        return Promise.reject(error);
      }
      const staleHeaders = originalRequest.headers as unknown as {
        delete?: (name: string) => void;
        [key: string]: unknown;
      };
      if (typeof staleHeaders.delete === 'function') {
        staleHeaders.delete('X-Company-Id');
      } else {
        delete staleHeaders['X-Company-Id'];
      }
      return api.request(originalRequest);
    }

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
          // Refresh tokens rotate, so the mobile app's stored pair is dead the
          // moment this one lands; it has to be told the new one.
          postToNative({ type: 'tokens', accessToken: nextAccessToken, refreshToken: nextRefreshToken });
          return nextAccessToken;
        })
        .catch((refreshError) => {
          localStorage.removeItem('token');
          localStorage.removeItem('refresh_token');
          // The mobile app is sent back to its native login only when the
          // server actually rejected the refresh token. A network error, timeout
          // or 5xx says nothing about the token, and the app re-injects its
          // stored pair on the next launch, which is what should happen then.
          // Concurrent 401s share this one refresh, so this posts once. The
          // no-refresh-token branch above deliberately does not post: it is only
          // reached once a session has already ended, and would repeat for
          // every later 401.
          const refreshStatus = axios.isAxiosError(refreshError) ? refreshError.response?.status : undefined;
          if (refreshStatus === 401 || refreshStatus === 403) {
            postToNative({ type: 'logout' });
          }
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

export type ApiFieldError = { field: string; message: string };

export type ApiErrorDetails = {
  /** Readable on its own, for a toast or a banner. */
  message: string;
  /** The same problems by field, when the API named the fields. */
  fieldErrors: ApiFieldError[];
};

// Pydantic's wording for the mistakes a form can make. Anything else keeps its own text.
const PLAIN_VALIDATION_MESSAGES: Record<string, string> = {
  missing: 'is required',
  int_parsing: 'must be a whole number',
  int_from_float: 'must be a whole number',
  int_type: 'must be a whole number',
  float_parsing: 'must be a number',
  float_type: 'must be a number',
  bool_parsing: 'must be yes or no',
  string_type: 'must be text',
  date_from_datetime_parsing: 'must be a valid date',
};

// Field names that read badly when only capitalised ("Gst", "Hsn sac").
const FIELD_WORDS: Record<string, string> = {
  gst: 'GSTIN',
  gstin: 'GSTIN',
  hsn_sac: 'HSN/SAC',
  pan: 'PAN',
  ifsc: 'IFSC',
  upi: 'UPI',
  pincode: 'PIN code',
  pin: 'PIN',
  id: 'ID',
};

function fieldLabel(field: string) {
  const known = FIELD_WORDS[field];
  if (known) return known;
  const words = field
    .split('_')
    .map((word) => FIELD_WORDS[word] ?? word)
    .join(' ')
    .trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "Invalid GSTIN format" already names the field; "Gst: Invalid GSTIN format" says it twice. */
function describeFieldError(field: string, text: string) {
  const label = fieldLabel(field);
  return text.toLowerCase().includes(label.toLowerCase()) ? text : `${label}: ${text}`;
}

/** FastAPI's own 422: `detail` is a list of {loc, msg, type}. */
function readValidationList(detail: unknown[]): ApiFieldError[] {
  return detail.flatMap((entry) => {
    const item = entry as { loc?: unknown[]; msg?: unknown; type?: unknown };
    if (typeof item?.msg !== 'string') return [];
    // loc is ['body', 'distance_km']; the last string is the field, and ['body'] alone names none.
    const path = (item.loc ?? []).filter((part): part is string => typeof part === 'string' && part !== 'body');
    const field = path[path.length - 1] ?? '';
    const text = item.msg.replace(/^Value error, /, '');
    const plain = typeof item.type === 'string' ? PLAIN_VALIDATION_MESSAGES[item.type] : undefined;
    if (!field) return [{ field: '', message: text }];
    return [{ field, message: plain ? `${fieldLabel(field)} ${plain}.` : describeFieldError(field, text) }];
  });
}

/** What a response's `detail` says, in every shape the API sends it, or null if it says nothing. */
function readDetail(detail: unknown): ApiErrorDetails | null {
  if (typeof detail === 'string' && detail) {
    return { message: detail, fieldErrors: [] };
  }
  if (Array.isArray(detail)) {
    const fieldErrors = readValidationList(detail);
    return fieldErrors.length ? { message: fieldErrors.map((e) => e.message).join(' '), fieldErrors } : null;
  }
  if (detail && typeof detail === 'object') {
    const { message, errors } = detail as { message?: unknown; errors?: unknown };
    // {message, errors: [{field, message}]}: the list is the useful part.
    const fieldErrors = Array.isArray(errors)
      ? errors.filter((e): e is ApiFieldError => typeof e?.field === 'string' && typeof e?.message === 'string')
      : [];
    if (fieldErrors.length) {
      return { message: fieldErrors.map((e) => e.message).join(' '), fieldErrors };
    }
    // Coded errors carry {code, message}; show the message.
    if (typeof message === 'string' && message) {
      return { message, fieldErrors: [] };
    }
  }
  return null;
}

export function getApiErrorMessage(error: unknown, fallback = 'Something went wrong') {
  if (axios.isAxiosError(error)) {
    const details = readDetail(error.response?.data?.detail);
    if (details) {
      return details.message;
    }
    // A response with nothing readable in it, like a proxy's HTML error page. Axios's
    // own message would only tell the user a status code.
    if (error.response) {
      return fallback;
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallback;
}

/** The machine code of a `detail: {code, message}` error, if the response has one. */
export function getApiErrorCode(error: unknown): string | null {
  if (axios.isAxiosError(error)) {
    const code = error.response?.data?.detail?.code;
    if (typeof code === 'string') {
      return code;
    }
  }
  return null;
}

/**
 * The message and any per-field errors of a failed request, whatever its responseType.
 * With responseType: 'blob' the server's JSON body arrives as a Blob on errors too, so
 * `detail` is not directly readable and has to be decoded first.
 */
export async function getApiErrorDetails(error: unknown, fallback = 'Something went wrong'): Promise<ApiErrorDetails> {
  if (axios.isAxiosError(error)) {
    let body: unknown = error.response?.data;
    if (body instanceof Blob) {
      try {
        body = JSON.parse(await body.text());
      } catch {
        // Body was not JSON — fall through to the generic handler.
        body = null;
      }
    }
    const details = readDetail((body as { detail?: unknown } | null | undefined)?.detail);
    if (details) {
      return details;
    }
  }
  return { message: getApiErrorMessage(error, fallback), fieldErrors: [] };
}

/** Like getApiErrorMessage, but for requests made with responseType: 'blob'. */
export async function getBlobErrorMessage(error: unknown, fallback = 'Something went wrong') {
  return (await getApiErrorDetails(error, fallback)).message;
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
