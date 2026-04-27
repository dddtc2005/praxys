/**
 * Tiny HTTP client over wx.request. Adds JWT injection, JSON serialization,
 * and a 401 → relaunch-to-login redirect so dead tokens don't loop pages
 * into a fetch-401-fetch cycle.
 *
 * API_BASE points at production by default so real-device preview works
 * without LAN debug bridge gymnastics. To run against a local backend,
 * swap to `http://localhost:8000` (or your laptop's LAN IP for real-device
 * over WiFi) and uvicorn must accept that origin.
 *
 * WeChat must whitelist the host in production via mp.weixin.qq.com → 开发
 * → 开发设置 → 服务器域名 (request合法域名). The simulator + DevTools can
 * bypass this via 详情 → 本地设置 → 不校验合法域名.
 */

export const API_BASE: string = 'https://api.praxys.run';

export const TOKEN_KEY = 'praxys-auth-token';

export interface ApiError {
  status: number;
  /** FastAPI's `detail` field if present; otherwise a generic message. */
  detail: string;
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

const LOGIN_PAGE = 'pages/login/index';

function authHeader(): Record<string, string> {
  const token = wx.getStorageSync<string>(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function isOnLoginPage(): boolean {
  // getCurrentPages() returns the in-memory page stack; the top of the
  // stack is the active page. Route strings are stored without a leading
  // slash. The wrapping try/catch covers the "no pages yet" edge case
  // when this runs during the very first onLaunch tick.
  try {
    const pages = getCurrentPages();
    const top = pages[pages.length - 1];
    return top?.route === LOGIN_PAGE;
  } catch {
    return false;
  }
}

function redirectToLogin(): void {
  wx.removeStorageSync(TOKEN_KEY);
  wx.reLaunch({
    url: `/${LOGIN_PAGE}`,
    fail: () => {
      // If the current page is already /pages/login/index the reLaunch
      // rejects with "redundant"; that's fine — we're already there.
    },
  });
}

// Override wx.request's 60s default — failures should surface quickly
// during dev so you don't wait a full minute when prod is unreachable
// or a host isn't whitelisted.
const REQUEST_TIMEOUT_MS = 30000;

function wxRequest(opts: WechatMiniprogram.RequestOption): Promise<WechatMiniprogram.RequestSuccessCallbackResult> {
  return new Promise((resolve, reject) => {
    wx.request({
      timeout: REQUEST_TIMEOUT_MS,
      ...opts,
      success: (res) => resolve(res),
      fail: (err) => reject(err),
    });
  });
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  let response: WechatMiniprogram.RequestSuccessCallbackResult;
  try {
    response = await wxRequest({
      url,
      method: (options.method ?? 'GET') as WechatMiniprogram.RequestOption['method'],
      data: options.body as WechatMiniprogram.RequestOption['data'],
      header: {
        'Content-Type': 'application/json',
        ...authHeader(),
        ...options.headers,
      },
    });
  } catch (e) {
    // wx.request fail callbacks deliver `{ errMsg: "request:fail ..." }`
    // — translate to our ApiError shape so the page error UI shows
    // something meaningful instead of "[object Object]".
    const errMsg =
      (e as { errMsg?: string })?.errMsg ?? (e instanceof Error ? e.message : String(e));
    throw { status: 0, detail: errMsg } as ApiError;
  }

  const status = response.statusCode;
  if (status === 401 && !options.skipAuthRedirect) {
    // If we're already on the login page, don't reLaunch (would no-op
    // with "redundant") and don't return a never-settling Promise — that
    // would hang the caller's loading state forever. Instead, clear the
    // dead token and surface the 401 so the login page's onLoad can react.
    if (isOnLoginPage()) {
      wx.removeStorageSync(TOKEN_KEY);
      throw { status: 401, detail: 'UNAUTHENTICATED' } as ApiError;
    }
    redirectToLogin();
    // The reLaunch unmounts the caller — the never-settling promise
    // keeps the awaiter from resolving into discarded state.
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
  throw { status, detail } as ApiError;
}

export const apiGet = <T>(path: string) => request<T>(path, { method: 'GET' });
export const apiPost = <T>(path: string, body?: unknown, opts?: RequestOptions) =>
  request<T>(path, { ...opts, method: 'POST', body });
export const apiPut = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PUT', body });
