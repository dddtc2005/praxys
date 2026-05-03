import {
  getToken,
  runLaunchLogin,
  saveToken,
  wechatLinkWithPassword,
} from '../../utils/auth';
import { apiPost } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import {
  applyThemeChrome,
  getThemePreference,
  setThemePreference,
  themeClassName,
} from '../../utils/theme';
import type { ThemePref } from '../../utils/theme';
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
 * Build the page's translation table once per mount. Most strings come
 * from web's lingui catalog (auto-synced via `sync-i18n.cjs`), with a
 * handful of mini-program-only keys (waitlist copy, theme-toggle aria
 * labels, tap-to-copy hints) living in `i18n-extra.ts`.
 *
 * The CTA text changes between idle and link stages on purpose:
 * - Idle: "Sign in with WeChat" (we don't yet know if the WeChat profile
 *   is bound to a Praxys account, but the action *is* a WeChat sign-in).
 * - Link: "Link to Praxys" (the user has a setup ticket; tapping the
 *   button binds their existing Praxys account).
 *
 * Tagline is split into three segments — `taglinePrefix +
 * taglineAccent + taglineSuffix` — so the green-accent span ("meets
 * you" / "知行合一") can be its own coloured `<text>` node. Skyline's
 * text composition can't put a coloured span inside a single text
 * node, so we render each segment separately and let the line wrap
 * naturally.
 */
function buildLoginTr(locale: Locale) {
  const taglinePrefix =
    locale === 'zh' ? '运动科学，' : 'Sports science that ';
  const taglineAccent = locale === 'zh' ? '知行合一' : 'meets you';
  const taglineSuffix = locale === 'zh' ? '。' : ' where you are.';

  return {
    taglinePrefix,
    taglineAccent,
    taglineSuffix,
    alphaEyebrow: t('Private alpha · Invitation only'),

    pillar1Strong: t("Today's signal."),
    pillar1Rest: t(' Go, modify, or rest.'),
    pillar2Strong: t('Diagnosis & forecast'),
    pillar2Rest: t(' you can verify.'),
    pillar3Strong: t('Cited science.'),
    pillar3Rest: t(' No hype.'),

    signInWeChat: t('Sign in with WeChat'),
    signingIn: t('Signing you in…'),
    signInFailed: t('Sign-in failed'),
    retry: t('Retry'),
    linkTitle: t('Sign in to Praxys'),
    linkDetail:
      locale === 'zh'
        ? '请输入您在 praxys.run 注册时使用的邮箱和密码。'
        : 'Use the email and password you registered with on praxys.run.',
    emailPlaceholder: t('email'),
    passwordPlaceholder: t('password'),
    linkAction: t('Link to Praxys'),

    newHere: t('New here?'),
    haveInviteCode: t('Have an invitation code?'),
    joinTheWaitlist: t('Join the waitlist'),
    backToSignIn: t('Back to sign in'),

    waitlistIntro: t(
      "We're inviting runners in waves while we tighten the science. Drop your email and we'll reach back when a slot opens.",
    ),
    waitlistNotePlaceholder: t('Sub-3 marathon · 100K · stay healthy…'),
    waitlistSuccessTitle: t("You're on the list."),
    waitlistSuccessDetail: t(
      "We'll reach out from support@praxys.run when a slot opens.",
    ),
    saving: t('Saving…'),

    waitlistEmailRequired: t('Email is required.'),
    waitlistRateLimited: t(
      'Too many attempts from this network. Please email us instead.',
    ),
    waitlistInvalidEmail: t('Please check your email format and try again.'),
    waitlistGenericFail: t(
      'Could not save your email. Please email us instead.',
    ),

    themeLight: t('Light theme'),
    themeDark: t('Dark theme'),
    themeAuto: t('System theme'),

    emailPasswordRequired: t('Email and password are required'),
  };
}

/**
 * Login page lifecycle:
 *   onLoad inspects storage:
 *     - token present  → reLaunch to /pages/today (auto-skip)
 *     - token missing  → show 'idle' stage with brand stack + Sign-in
 *                        CTA + waitlist footer.
 *
 *   User taps Sign in → wx.login() → /api/auth/wechat/login
 *     - status 'ok' + access_token: save JWT, reLaunch to /pages/today.
 *     - status 'needs_setup' + ticket: show the link-to-existing-account
 *       form (CTA "Link to Praxys"). Account creation lives on
 *       praxys.run.
 *     - failure: show error + retry button.
 *
 *   User taps "Join the waitlist" → 'waitlist' stage with email +
 *     optional note inputs. Submitting calls POST /api/auth/waitlist
 *     (per CLAUDE.md, this is the one registration-adjacent write the
 *     miniapp owns — email-only intent capture, no platform OAuth).
 *     Success → 'waitlist-success' stage with back-to-sign-in CTA.
 *
 * Why no register stage in the mini program: the full onboarding flow
 * (platform connections, training base, threshold setup) lives on web.
 * Sending users with an invitation code to praxys.run keeps the mini
 * program focused on view + manage for already-registered users.
 */

type Stage =
  | 'idle'
  | 'loading'
  | 'choose'
  | 'link'
  | 'error'
  | 'waitlist'
  | 'waitlist-success';

interface PageData {
  stage: Stage;
  themeClass: string;
  themePref: ThemePref;
  ticket: string;
  errorMessage: string;
  /** Resolved locale ('en' | 'zh'); drives the active state on the
   *  top-left language toggle and selects the description copy. */
  locale: Locale;

  linkEmail: string;
  linkPassword: string;
  linkSubmitting: boolean;
  linkError: string;

  waitlistEmail: string;
  waitlistNote: string;
  waitlistSubmitting: boolean;
  waitlistError: string;

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
  onSwitchTheme(e: WechatMiniprogram.TouchEvent): void;
  onWaitlistTap(): void;
  onWaitlistEmailInput(e: WechatMiniprogram.Input): void;
  onWaitlistNoteInput(e: WechatMiniprogram.Input): void;
  onWaitlistSubmit(): Promise<void>;
  onWaitlistBack(): void;
}

const initialLocale: Locale = 'zh';

const initialData: PageData = {
  stage: 'idle',
  themeClass: getApp<IAppOption>().globalData.themeClass,
  themePref: 'auto',
  ticket: '',
  errorMessage: '',
  locale: initialLocale,
  linkEmail: '',
  linkPassword: '',
  linkSubmitting: false,
  linkError: '',
  waitlistEmail: '',
  waitlistNote: '',
  waitlistSubmitting: false,
  waitlistError: '',
  tr: buildLoginTr(initialLocale),
};

Page<PageData, PageMethods>({
  data: { ...initialData },

  onLoad() {
    const locale = detectLocale();
    this.setData({
      themeClass: themeClassName(),
      themePref: getThemePreference(),
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
   * Tap on the "Join the waitlist" footer row. Drops into the
   * waitlist stage with empty form state — every entry to the
   * waitlist starts fresh (no carry-over from a prior abandoned
   * attempt).
   */
  onWaitlistTap() {
    this.setData({
      stage: 'waitlist',
      waitlistEmail: '',
      waitlistNote: '',
      waitlistError: '',
      waitlistSubmitting: false,
    });
  },

  onWaitlistEmailInput(e) {
    this.setData({ waitlistEmail: e.detail.value });
  },
  onWaitlistNoteInput(e) {
    this.setData({ waitlistNote: e.detail.value });
  },

  /**
   * Submit to /api/auth/waitlist. Mirrors web's handleWaitlistSubmit
   * (rate-limit, validation, generic-fail handling) — surfaces the
   * same in-page success state on the next render.
   */
  async onWaitlistSubmit() {
    const { waitlistEmail, waitlistNote, locale, tr } = this.data;
    const email = waitlistEmail.trim();
    if (!email) {
      this.setData({ waitlistError: tr.waitlistEmailRequired });
      return;
    }
    this.setData({ waitlistSubmitting: true, waitlistError: '' });
    try {
      await apiPost(
        '/api/auth/waitlist',
        {
          email,
          note: waitlistNote.trim().slice(0, 500),
          locale,
        },
        { skipAuthRedirect: true },
      );
      this.setData({
        stage: 'waitlist-success',
        waitlistSubmitting: false,
        waitlistEmail: '',
        waitlistNote: '',
      });
    } catch (e) {
      const err = e as Partial<ApiError>;
      let msg = tr.waitlistGenericFail;
      if (err.status === 429) msg = tr.waitlistRateLimited;
      else if (err.status === 422) msg = tr.waitlistInvalidEmail;
      else if (typeof err.detail === 'string' && err.detail) msg = err.detail;
      this.setData({ waitlistSubmitting: false, waitlistError: msg });
    }
  },

  onWaitlistBack() {
    this.setData({
      stage: 'idle',
      waitlistEmail: '',
      waitlistNote: '',
      waitlistError: '',
      waitlistSubmitting: false,
    });
  },

  /**
   * "New here?" / "Have an invitation code?" rows tap to copy the
   * praxys.run URL to clipboard. WeChat doesn't let mini programs
   * open external URLs in the system browser, so the UX is "copy the
   * URL → user opens it in their browser of choice".
   */
  onCopySignupUrl() {
    wx.setClipboardData({
      data: SIGNUP_URL,
      success: () => {
        wx.showToast({ title: t('URL copied'), icon: 'success', duration: 1500 });
      },
    });
  },

  /**
   * Top-left language toggle. Mirror of web's LanguageToggle: writes
   * the new preference to wx storage and reLaunches the page so every
   * `t()` call resolves against the new catalog.
   */
  onSwitchLang(e) {
    const next = e.currentTarget.dataset.lang as Locale | undefined;
    if (!next || next === this.data.locale) return;
    setLanguagePreference(next);
    wx.reLaunch({ url: '/pages/login/index' });
  },

  /**
   * Top-left theme toggle. Three-state pill (light / dark / auto) —
   * tap on a segment to make it active. Persists the preference to
   * wx storage and reLaunches the page so the new theme class
   * applies everywhere consistently.
   */
  onSwitchTheme(e) {
    const next = e.currentTarget.dataset.theme as ThemePref | undefined;
    if (!next || next === this.data.themePref) return;
    setThemePreference(next);
    wx.reLaunch({ url: '/pages/login/index' });
  },
});
