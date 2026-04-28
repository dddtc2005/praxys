import {
  getToken,
  runLaunchLogin,
  saveToken,
  wechatLinkWithPassword,
} from '../../utils/auth';
import type { ApiError } from '../../utils/api-client';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { detectShareLocale, getShareMessage } from '../../utils/share';
import { t } from '../../utils/i18n';

const SIGNUP_URL = 'https://www.praxys.run';

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

function buildLoginTr() {
  return {
    tagline: t('Sports science that meets you where you are.'),
    welcomeBack: t('Welcome back'),
    idleDetail: t(
      'Power-based training, on your wrist or in your pocket. Sign in with WeChat to access your training data.',
    ),
    signInWeChat: t('Sign in with WeChat'),
    signingIn: t('Signing you in…'),
    signInFailed: t('Sign-in failed'),
    retry: t('Retry'),
    linkTitle: t('Sign in to Praxys'),
    linkDetail: t(
      'Use the email and password you registered with on praxys.run.',
    ),
    emailPlaceholder: t('email'),
    passwordPlaceholder: t('password'),
    linkAction: t('Sign in'),
    newHere: t('New here? Sign up at'),
    tapToCopyUrl: t('tap to copy URL'),
    urlCopied: t('URL copied'),
    emailPasswordRequired: t('Email and password are required'),
  };
}

/**
 * Login page lifecycle:
 *   onLoad inspects storage:
 *     - token present  → reLaunch to /pages/today (auto-skip)
 *     - token missing  → show 'idle' stage with "Sign in with WeChat".
 *
 *   User taps Sign in → wx.login() → /api/auth/wechat/login
 *     - status 'ok' + access_token: save JWT, reLaunch to /pages/today.
 *     - status 'needs_setup' + ticket: show the sign-in (link) form.
 *       Account creation lives on praxys.run; the form has a "new here?"
 *       row that copies the signup URL to clipboard.
 *     - failure: show error + retry button.
 *
 * The 'idle' stage is what makes sign-out actually log the user out:
 * with a token present, the auto-skip kicks in; clearing the token in
 * Settings → Switch / Sign out lands here in idle, and the user must
 * explicitly tap to re-auth.
 *
 * Why no register stage in the mini program: the full onboarding flow
 * (platform connections, training base, threshold setup) lives on web.
 * Sending a brand-new WeChat user to praxys.run keeps the mini program
 * focused on view + manage for already-registered users.
 */

type Stage = 'idle' | 'loading' | 'choose' | 'link' | 'error';

interface PageData {
  stage: Stage;
  themeClass: string;
  ticket: string;
  errorMessage: string;

  linkEmail: string;
  linkPassword: string;
  linkSubmitting: boolean;
  linkError: string;

  tr: ReturnType<typeof buildLoginTr>;
}

interface PageMethods extends WechatMiniprogram.IAnyObject {
  onSignInTap(): void;
  runLogin(): Promise<void>;
  onRetry(): void;
  onLinkEmailInput(e: WechatMiniprogram.Input): void;
  onLinkPasswordInput(e: WechatMiniprogram.Input): void;
  onLinkSubmit(): Promise<void>;
  onCopySignupUrl(): void;
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
  tr: buildLoginTr(),
};

Page<PageData, PageMethods>({
  data: { ...initialData },

  onLoad() {
    this.setData({ themeClass: themeClassName(), tr: buildLoginTr() });
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
        // Skip the choose-link-or-register split — register lives on web.
        this.setData({ stage: 'link', ticket: result.wechat_login_ticket });
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

  onLinkEmailInput(e) {
    this.setData({ linkEmail: e.detail.value });
  },
  onLinkPasswordInput(e) {
    this.setData({ linkPassword: e.detail.value });
  },

  async onLinkSubmit() {
    const { linkEmail, linkPassword, ticket, tr } = this.data;
    if (!linkEmail || !linkPassword) {
      this.setData({ linkError: tr.emailPasswordRequired });
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

  /**
   * "New here?" row taps copy the signup URL to clipboard. WeChat doesn't
   * let mini programs open external URLs in the system browser, so the
   * UX is "copy the URL → user opens it in their browser of choice".
   */
  onCopySignupUrl() {
    const tr = this.data.tr;
    wx.setClipboardData({
      data: SIGNUP_URL,
      success: () => {
        wx.showToast({ title: tr.urlCopied, icon: 'success', duration: 1500 });
      },
    });
  },
});
