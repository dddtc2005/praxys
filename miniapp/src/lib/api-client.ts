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
 * config/index.ts, which runs `process.env.API_BASE` through webpack's
 * DefinePlugin — so the reference below is substituted with a string
 * literal at compile time. No runtime `process` access happens inside
 * WeChat (where `process` is undefined), which is why the old
 * `typeof process !== 'undefined'` guard was a bug: it evaluated to
 * false at runtime and silently fell through to the fallback.
 *
 * Default: localhost:8000 (matches `uvicorn api.main:app --reload`).
 */
export const API_BASE: string = process.env.API_BASE || 'http://localhost:8000';

export const TOKEN_KEY = 'praxys-auth-token';

export interface ApiError {
  status: number;
  /** FastAPI's `detail` field if present; otherwise a generic message. */
  detail: string;
}

function authHeader(): Record<string, string> {
  const token = Taro.getStorageSync(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

const LOGIN_PAGE = 'pages/login/index';

function isOnLoginPage(): boolean {
  // Taro.getCurrentPages() returns the in-memory page stack; the top of
  // the stack is the active page. Route strings are stored without a
  // leading slash.
  try {
    const pages = Taro.getCurrentPages();
    const top = pages[pages.length - 1];
    return top?.route === LOGIN_PAGE;
  } catch {
    return false;
  }
}

/**
 * Redirect to the login page when the stored JWT is rejected. We relaunch
 * instead of navigateTo so the login page can't be dismissed back into
 * the authenticated tab stack.
 */
function redirectToLogin(): void {
  Taro.removeStorageSync(TOKEN_KEY);
  Taro.reLaunch({ url: `/${LOGIN_PAGE}` }).catch(() => {
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
    // If we're already on the login page, don't relaunch (would be a no-op
    // that rejects with "redundant") and don't return a never-settling
    // Promise — that would hang the caller's loading state forever.
    // Instead, clear the dead token and surface the 401 as a real error so
    // the login page's effect can react to it.
    if (isOnLoginPage()) {
      Taro.removeStorageSync(TOKEN_KEY);
      throw { status: 401, detail: 'UNAUTHENTICATED' } as ApiError;
    }
    redirectToLogin();
    // The reLaunch unmounts the caller — the never-settling promise keeps
    // the awaiter from resolving into discarded state.
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
