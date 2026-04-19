import Taro from '@tarojs/taro';
import { apiPost, TOKEN_KEY } from '@/lib/api-client';

/**
 * Three-endpoint WeChat auth flow, mirroring api/routes/wechat.py:
 *
 *   POST /api/auth/wechat/login                  → {status, access_token?, wechat_login_ticket?}
 *   POST /api/auth/wechat/link-with-password     → {access_token}
 *   POST /api/auth/wechat/register               → {access_token}
 *
 * Stored token is attached to every subsequent Taro.request by
 * api-client.ts. A 401 response clears the token and reLaunches to login.
 */

export interface WeChatLoginResponse {
  status: 'ok' | 'needs_setup';
  access_token?: string | null;
  wechat_login_ticket?: string | null;
}

export interface WeChatAuthResponse {
  access_token: string;
}

export function saveToken(token: string): void {
  Taro.setStorageSync(TOKEN_KEY, token);
}

export function clearToken(): void {
  Taro.removeStorageSync(TOKEN_KEY);
}

export function getToken(): string {
  return Taro.getStorageSync(TOKEN_KEY) || '';
}

/**
 * Exchange a Tencent js_code for either a JWT (returning user) or a
 * setup ticket (new-to-this-app). The caller decides what to do with
 * the result.
 */
export async function wechatLogin(jsCode: string): Promise<WeChatLoginResponse> {
  const body = { js_code: jsCode };
  return apiPost<WeChatLoginResponse>('/api/auth/wechat/login', body, {
    skipAuthRedirect: true,
  });
}

export async function wechatLinkWithPassword(
  ticket: string,
  email: string,
  password: string,
): Promise<WeChatAuthResponse> {
  return apiPost<WeChatAuthResponse>(
    '/api/auth/wechat/link-with-password',
    { wechat_login_ticket: ticket, email, password },
    { skipAuthRedirect: true },
  );
}

export async function wechatRegister(
  ticket: string,
  invitationCode: string,
  email?: string,
  password?: string,
  nickname?: string,
  avatarUrl?: string,
): Promise<WeChatAuthResponse> {
  return apiPost<WeChatAuthResponse>(
    '/api/auth/wechat/register',
    {
      wechat_login_ticket: ticket,
      invitation_code: invitationCode,
      email: email || null,
      password: password || null,
      nickname: nickname || null,
      avatar_url: avatarUrl || null,
    },
    { skipAuthRedirect: true },
  );
}

/**
 * Run the full launch sequence: `Taro.login()` → `/api/auth/wechat/login`.
 * Throws if the code exchange fails; otherwise returns the result for
 * the login page to route on (status === 'ok' goes to today, anything
 * else shows the onboarding step).
 */
export async function runLaunchLogin(): Promise<WeChatLoginResponse> {
  const { code } = await Taro.login();
  if (!code) throw new Error('WECHAT_NO_LOGIN_CODE');
  return wechatLogin(code);
}
