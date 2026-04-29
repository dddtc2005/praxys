import {
  getToken,
  runLaunchLogin,
  saveToken,
  wechatLinkWithPassword,
} from '../../utils/auth';
import type { ApiError } from '../../utils/api-client';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { detectShareLocale, getShareMessage, setLanguagePreference } from '../../utils/share';
import { detectLocale, t } from '../../utils/i18n';
import type { Locale } from '../../utils/i18n-catalog';
import type { IAppOption } from '../../app';

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

/**
 * Build the page's translation table once per mount. The long
 * description and the link-stage copy aren't in web's lingui catalog
 * yet (they're mini-program-specific framing), so we choose by locale
 * instead of relying on the auto-synced catalog. Everything else routes
 * through `t()` so future catalog updates pick up automatically.
 *
 * The CTA text changes between idle and link stages on purpose:
 * - Idle: "Sign in with WeChat" (we don't yet know if the WeChat profile
 *   is bound to a Praxys account, but the action *is* a WeChat sign-in)
 * - Link: "Link to Praxys" (the user has a setup ticket; tapping the
 *   button binds their existing Praxys account, which "Sign in" doesn't
 *   convey clearly)
 */
function buildLoginTr(locale: Locale) {
  const description =
    locale === 'zh'
      ? 'Praxys 把您的每次跑步变成有科学依据的洞察、个性化的训练区间，以及随您一起成长的训练计划。每一位跑者——从公路到越野，从首跑者到老将——都值得拥有。'
      : 'Praxys turns your runs into science-grounded insights, personalized zones, and a training plan that evolves with you. For every runner — road to trail, first-timer to veteran.';
  const linkDetail =
    locale === 'zh'
      ? '请输入您在 praxys.run 注册时使用的邮箱和密码。'
      : 'Use the email and password you registered with on praxys.run.';
  return {
    // Hero — already in the lingui catalog because it's the share copy.
    hero: t('Train like a pro. Whatever your level.'),
    description,
    signInWeChat: t('Sign in with WeChat'),
    signingIn: t('Signing you in…'),
    signInFailed: t('Sign-in failed'),
    retry: t('Retry'),
    linkTitle: t('Sign in to Praxys'),
    linkDetail,
    emailPlaceholder: t('email'),
    passwordPlaceholder: t('password'),
    // The link-form CTA differs from the idle CTA — see the function
    // docstring for why.
    linkAction: t('Link to Praxys'),
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
 *     - status 'needs_setup' + ticket: show the link-to-existing-account
 *       form (CTA "Link to Praxys"). Account creation lives on
 *       praxys.run; the form has a "new here?" row that copies the
 *       signup URL to clipboard.
 *     - failure: show error + retry button.
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
  /** Resolved locale ('en' | 'zh'); drives the active state on the
   *  top-right language toggle and selects the description copy. */
  locale: Locale;

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
  onSwitchLang(e: WechatMiniprogram.TouchEvent): void;
}

const initialLocale: Locale = 'zh';

const initialData: PageData = {
  stage: 'idle',
  themeClass: getApp<IAppOption>().globalData.themeClass,
  ticket: '',
  errorMessage: '',
  locale: initialLocale,
  linkEmail: '',
  linkPassword: '',
  linkSubmitting: false,
  linkError: '',
  tr: buildLoginTr(initialLocale),
};

Page<PageData, PageMethods>({
  data: { ...initialData },

  onLoad() {
    const locale = detectLocale();
    this.setData({
      themeClass: themeClassName(),
      locale,
      tr: buildLoginTr(locale),
    });
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

  /**
   * Top-right language toggle. Mirror of web's LanguageToggle: writes
   * the new preference to wx storage and reLaunches the page so every
   * `t()` call resolves against the new catalog. We deliberately don't
   * try to hot-swap the catalog in place — the per-page cached `tr`
   * tables would still show the old locale until each page rebuilt.
   */
  onSwitchLang(e) {
    const next = e.currentTarget.dataset.lang as Locale | undefined;
    if (!next || next === this.data.locale) return;
    setLanguagePreference(next);
    wx.reLaunch({ url: '/pages/login/index' });
  },
});
