import Taro from '@tarojs/taro';

/**
 * API base URL. Point this at your dev server when testing in WeChat
 * DevTools (simulator allows 不校验合法域名); for production the domain
 * must be whitelisted in the mini-program console.
 *
 * Override at build time:
 *   API_BASE=http://192.168.1.5:8000 npm run build:weapp
 *
 * The value is baked into the bundle via `defineConstants` in
 * config/index.ts — mini programs don't have runtime environment
 * variables, so this has to happen at compile time.
 *
 * Default: localhost:8000 (matches `uvicorn api.main:app --reload`).
 */
export const API_BASE: string =
  (typeof process !== 'undefined' && (process.env.API_BASE as string | undefined)) ||
  'http://localhost:8000';

export const TOKEN_KEY = 'trainsight-auth-token';

export interface ApiError {
  status: number;
  /** FastAPI's `detail` field if present; otherwise a generic message. */
  detail: string;
}

function authHeader(): Record<string, string> {
  const token = Taro.getStorageSync(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Redirect to the login page when the stored JWT is rejected. We relaunch
 * instead of navigateTo so the login page can't be dismissed back into
 * the authenticated tab stack.
 */
function redirectToLogin(): void {
  Taro.removeStorageSync(TOKEN_KEY);
  Taro.reLaunch({ url: '/pages/login/index' }).catch(() => {
    // If the current page is already /pages/login/index the reLaunch
    // rejects with "redundant"; that's fine — we're already there.
  });
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  /**
   * Skip the 401 → login redirect. Set this on the /auth/wechat/login call
   * itself (expected to be unauthenticated) so we don't loop.
   */
  skipAuthRedirect?: boolean;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const response = await Taro.request({
    url,
    method: (options.method ?? 'GET') as 'GET',
    data: options.body,
    header: {
      'Content-Type': 'application/json',
      ...authHeader(),
      ...options.headers,
    },
  });

  const status = response.statusCode;
  if (status === 401 && !options.skipAuthRedirect) {
    redirectToLogin();
    return new Promise<T>(() => {});
  }

  if (status >= 200 && status < 300) {
    return response.data as T;
  }

  const rawDetail = (response.data as { detail?: unknown } | null | undefined)?.detail;
  const detail =
    typeof rawDetail === 'string'
      ? rawDetail
      : rawDetail != null
        ? JSON.stringify(rawDetail)
        : `HTTP ${status}`;
  const err: ApiError = { status, detail };
  throw err;
}

export const apiGet = <T>(path: string) => request<T>(path, { method: 'GET' });
export const apiPost = <T>(path: string, body?: unknown, opts?: RequestOptions) =>
  request<T>(path, { ...opts, method: 'POST', body });
export const apiPut = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PUT', body });
