import {
  getToken,
  runLaunchLogin,
  saveToken,
  wechatLinkWithPassword,
  wechatRegister,
} from '../../utils/auth';
import type { ApiError } from '../../utils/api-client';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { detectShareLocale, getShareMessage } from '../../utils/share';
import { t } from '../../utils/i18n';

/**
 * Map auth-flow error codes to user-facing copy. Untranslated machine
 * codes ("WECHAT_NO_LOGIN_CODE") are useless to the user; we fall back
 * to the original detail when there's no mapping so backend FastAPI
 * `detail` strings still surface verbatim.
 */
function friendlyAuthError(detail: string): string {
  if (detail === 'WECHAT_NO_LOGIN_CODE') {
    return t('Sign-in code unavailable. Please try again.');
  }
  if (detail === 'WECHAT_NOT_CONFIGURED') {
    return t('WeChat sign-in is not configured on this server.');
  }
  if (detail === 'UNAUTHENTICATED') {
    return t('Your session expired. Please sign in again.');
  }
  return detail;
}

/**
 * Login page lifecycle:
 *   onLoad inspects storage:
 *     - token present  → reLaunch to /pages/today (auto-skip)
 *     - token missing  → show 'idle' stage with "Sign in with WeChat" button.
 *
 *   User taps Sign in → wx.login() → /api/auth/wechat/login
 *     - status 'ok' + access_token: save JWT, reLaunch to /pages/today
 *     - status 'needs_setup' + ticket: show choose-account-or-register
 *     - failure: show error + retry button
 *
 * The 'idle' stage is what makes sign-out actually log the user out: with
 * a token present, the auto-skip kicks in; clearing the token in onSignOut
 * lands here in idle state, and the user must explicitly tap to re-auth.
 */

type Stage = 'idle' | 'loading' | 'choose' | 'link' | 'register' | 'error';

interface PageData {
  stage: Stage;
  themeClass: string;
  ticket: string;
  errorMessage: string;

  linkEmail: string;
  linkPassword: string;
  linkSubmitting: boolean;
  linkError: string;

  regInvitation: string;
  regEmail: string;
  regPassword: string;
  regSubmitting: boolean;
  regError: string;
}

interface PageMethods extends WechatMiniprogram.IAnyObject {
  onSignInTap(): void;
  runLogin(): Promise<void>;
  onRetry(): void;
  goChooseLink(): void;
  goChooseRegister(): void;
  goBackToChoose(): void;
  onLinkEmailInput(e: WechatMiniprogram.Input): void;
  onLinkPasswordInput(e: WechatMiniprogram.Input): void;
  onLinkSubmit(): Promise<void>;
  onRegInvitationInput(e: WechatMiniprogram.Input): void;
  onRegEmailInput(e: WechatMiniprogram.Input): void;
  onRegPasswordInput(e: WechatMiniprogram.Input): void;
  onRegSubmit(): Promise<void>;
}

const initialData: PageData = {
  stage: 'idle',
  themeClass: 'theme-light',
  ticket: '',
  errorMessage: '',
  linkEmail: '',
  linkPassword: '',
  linkSubmitting: false,
  linkError: '',
  regInvitation: '',
  regEmail: '',
  regPassword: '',
  regSubmitting: false,
  regError: '',
};

Page<PageData, PageMethods>({
  data: { ...initialData },

  onLoad() {
    this.setData({ themeClass: themeClassName() });
    // Auto-skip if a JWT is already stored (returning user). Otherwise
    // sit in 'idle' until the user taps Sign in — this is what makes
    // sign-out work. Without this check we'd silently re-authenticate.
    if (getToken()) {
      wx.reLaunch({ url: '/pages/today/index' });
      return;
    }
  },

  onSignInTap() {
    this.setData({ stage: 'loading', errorMessage: '' });
    void this.runLogin();
  },

  onShow() {
    applyThemeChrome();
  },

  onShareAppMessage() {
    return getShareMessage(detectShareLocale(), '/pages/login/index');
  },

  async runLogin() {
    try {
      const result = await runLaunchLogin();
      if (result.status === 'ok' && result.access_token) {
        saveToken(result.access_token);
        wx.reLaunch({ url: '/pages/today/index' });
        return;
      }
      if (result.status === 'needs_setup' && result.wechat_login_ticket) {
        this.setData({ stage: 'choose', ticket: result.wechat_login_ticket });
        return;
      }
      this.setData({ stage: 'error', errorMessage: 'Unexpected login response' });
    } catch (e) {
      const detail = (e as Partial<ApiError>)?.detail ?? String(e);
      this.setData({ stage: 'error', errorMessage: friendlyAuthError(detail) });
    }
  },

  onRetry() {
    this.setData({ stage: 'loading', errorMessage: '' });
    void this.runLogin();
  },

  goChooseLink() {
    this.setData({ stage: 'link', linkError: '' });
  },

  goChooseRegister() {
    this.setData({ stage: 'register', regError: '' });
  },

  goBackToChoose() {
    this.setData({ stage: 'choose' });
  },

  onLinkEmailInput(e) {
    this.setData({ linkEmail: e.detail.value });
  },
  onLinkPasswordInput(e) {
    this.setData({ linkPassword: e.detail.value });
  },

  async onLinkSubmit() {
    const { linkEmail, linkPassword, ticket } = this.data;
    if (!linkEmail || !linkPassword) {
      this.setData({ linkError: 'Email and password are required' });
      return;
    }
    this.setData({ linkSubmitting: true, linkError: '' });
    try {
      const r = await wechatLinkWithPassword(ticket, linkEmail, linkPassword);
      saveToken(r.access_token);
      wx.reLaunch({ url: '/pages/today/index' });
    } catch (e) {
      this.setData({
        linkSubmitting: false,
        linkError: friendlyAuthError((e as Partial<ApiError>)?.detail ?? String(e)),
      });
    }
  },

  onRegInvitationInput(e) {
    this.setData({ regInvitation: e.detail.value.toUpperCase() });
  },
  onRegEmailInput(e) {
    this.setData({ regEmail: e.detail.value });
  },
  onRegPasswordInput(e) {
    this.setData({ regPassword: e.detail.value });
  },

  async onRegSubmit() {
    const { regInvitation, regEmail, regPassword, ticket } = this.data;
    this.setData({ regSubmitting: true, regError: '' });
    try {
      const r = await wechatRegister(
        ticket,
        regInvitation,
        regEmail || undefined,
        regPassword || undefined,
      );
      saveToken(r.access_token);
      wx.reLaunch({ url: '/pages/today/index' });
    } catch (e) {
      this.setData({
        regSubmitting: false,
        regError: friendlyAuthError((e as Partial<ApiError>)?.detail ?? String(e)),
      });
    }
  },
});
