import { setTabBarSelected } from '../../utils/tabbar';
import { apiGet, apiPost, apiPut } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import { clearToken } from '../../utils/auth';
import {
  applyThemeChrome,
  getThemePreference,
  setThemePreference,
  themeClassName,
} from '../../utils/theme';
import type { ThemePref } from '../../utils/theme';
import type { IAppOption } from '../../app';
import { getLanguagePreference, setLanguagePreference } from '../../utils/share';
import { t } from '../../utils/i18n';
import type { SettingsResponse } from '../../types/api';

/**
 * Return the URL to reLaunch to after a theme or language change.
 * We reLaunch to whatever tab page the user is currently on — not
 * always to Settings — so the switch feels transparent rather than
 * ejecting the user to a different page.
 *
 * Tab bar pages have stable routes; sub-pages (Science) aren't tab
 * entries so we fall back to Settings.
 */
const TAB_ROUTES = new Set([
  'pages/today/index',
  'pages/training/index',
  'pages/goal/index',
  'pages/history/index',
  'pages/settings/index',
]);

// Storage key for scroll position persistence across reLaunch.
const SCROLL_RESTORE_KEY = 'praxys-scroll-restore';

function relaunchUrl(): string {
  try {
    const pages = getCurrentPages();
    const top = pages[pages.length - 1];
    if (top?.route && TAB_ROUTES.has(top.route)) {
      return `/${top.route}`;
    }
  } catch { /* fall through */ }
  return '/pages/settings/index';
}

/**
 * Save the current page's scroll position to storage so that the
 * next reLaunch can restore it. Call this immediately before wx.reLaunch.
 * Only persists for the Settings page — other tab pages start fresh.
 */
function saveScrollBefore(scrollY: number, targetUrl: string) {
  if (!targetUrl.includes('settings')) return; // only restore on settings
  try {
    wx.setStorageSync(SCROLL_RESTORE_KEY, JSON.stringify({ top: scrollY }));
  } catch { /* ignore */ }
}

function popSavedScroll(): number {
  try {
    const raw = wx.getStorageSync<string>(SCROLL_RESTORE_KEY) || '';
    wx.removeStorageSync(SCROLL_RESTORE_KEY); // one-shot: consume after reading
    const parsed = JSON.parse(raw) as { top?: number };
    return typeof parsed.top === 'number' ? parsed.top : 0;
  } catch {
    return 0;
  }
}

function buildSettingsTr() {
  return {
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    profile: t('Profile'),
    name: t('Name'),
    units: t('Units'),
    trainingBase: t('Training base'),
    connections: t('Connections'),
    manageOnWeb: t('Manage connections from the web app.'),
    noPlatformsHint: t(
      "No platforms connected. Link Garmin / Stryd / Oura from the web app — their OAuth flows aren't supported in mini programs.",
    ),
    thresholds: t('Thresholds'),
    thresholdsHint: t('Auto-detected from synced fitness data; override on the web.'),
    thresholdsEmpty: t(
      'No thresholds yet. Sync Garmin / Stryd data to auto-detect CP, LTHR, and pace — or enter values manually on the web.',
    ),
    trainingScience: t('Training Science'),
    scienceSubtitle: t('Browse the load / recovery / prediction / zone theories'),
    theme: t('Theme'),
    themeAuto: t('Auto'),
    themeDark: t('Dark'),
    themeLight: t('Light'),
    language: t('Language'),
    languageAuto: t('Auto'),
    openOnWeb: t('Open Praxys on web'),
    signOut: t('Log out'),
    switchAccount: t('Switch Praxys account'),
    switchAccountHint: t(
      'Unbind your WeChat profile from this Praxys account so you can sign in as a different user.',
    ),
    switchAccountFailed: t(
      "Couldn't unlink your account on the server. Try again in a moment, or sign out instead and contact support if it keeps failing.",
    ),
    connected: t('Connected'),
    syncNow: t('Sync now'),
    syncing: t('Syncing…'),
    syncStarted: t('Sync started in the background.'),
    syncFailed: t('Sync request failed. Try again from the web app if it persists.'),
    trainingBaseHint: t(
      'What metric Praxys uses to measure intensity. Power needs Stryd; Pace works with anything that gives you GPS.',
    ),
    trainingBasePower: t('Power'),
    trainingBaseHr: t('Heart rate'),
    trainingBasePace: t('Pace'),
  };
}

type LanguagePref = 'auto' | 'en' | 'zh';

const WEB_URL = 'https://www.praxys.run';

// Always iterate the known threshold keys rather than whatever the
// backend returns verbatim. The raw config.thresholds dict includes meta
// fields like `source` that aren't thresholds and would otherwise render
// as bogus rows.
const KNOWN_THRESHOLDS = [
  'cp_watts',
  'lthr_bpm',
  'threshold_pace_sec_km',
  'max_hr_bpm',
  'rest_hr_bpm',
] as const;

const THRESHOLD_LABEL: Record<string, string> = {
  cp_watts: 'CP',
  lthr_bpm: 'LTHR',
  threshold_pace_sec_km: 'Threshold pace',
  max_hr_bpm: 'Max HR',
  rest_hr_bpm: 'Resting HR',
};

const THRESHOLD_UNIT: Record<string, string> = {
  cp_watts: 'W',
  lthr_bpm: 'bpm',
  threshold_pace_sec_km: 'min/km',
  max_hr_bpm: 'bpm',
  rest_hr_bpm: 'bpm',
};

interface ProfileRow {
  label: string;
  value: string;
}

interface ConnectionRow {
  key: string;
  label: string;
}

interface ThresholdRow {
  key: string;
  label: string;
  display: string;
  hasOrigin: boolean;
  origin: string;
}

interface ThemeOption {
  key: ThemePref;
  label: string;
  className: string;
}

interface LanguageOption {
  key: LanguagePref;
  label: string;
  className: string;
}

interface SettingsState {
  themeClass: string;
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;
  theme: ThemePref;
  /** Human-readable label for the active theme, e.g. "Auto" or "Dark". */
  themeLabel: string;
  language: LanguagePref;
  /** Human-readable label for the active language, e.g. "Auto" or "中文". */
  languageLabel: string;

  profileRows: ProfileRow[];
  hasConnections: boolean;
  connectionRows: ConnectionRow[];

  hasThresholds: boolean;
  thresholdRows: ThresholdRow[];

  trainingBase: 'power' | 'hr' | 'pace';
  /** Human-readable label for the active training base, e.g. "Power". */
  trainingBaseLabel: string;

  webUrl: string;

  // Manual sync trigger UI state.
  syncing: boolean;
  syncMessage: string;

  // Scroll position restore — set once in onLoad, then zeroed so
  // subsequent programmatic setData calls don't re-trigger scroll.
  restoreScrollTop: number;
}

interface TrainingBaseOption {
  key: 'power' | 'hr' | 'pace';
  label: string;
  className: string;
}

function themeLabelFor(pref: ThemePref): string {
  if (pref === 'dark') return t('Dark');
  if (pref === 'light') return t('Light');
  return t('Auto');
}

function languageLabelFor(pref: LanguagePref): string {
  if (pref === 'en') return 'English';
  if (pref === 'zh') return '中文';
  return t('Auto');
}

function trainingBaseLabelFor(base: string): string {
  if (base === 'power') return t('Power');
  if (base === 'hr') return t('Heart rate');
  return t('Pace');
}

const initialData: SettingsState = {
  themeClass: getApp<IAppOption>().globalData.themeClass,
  loading: true,
  errorMessage: '',
  hasResponse: false,
  theme: 'auto',
  themeLabel: t('Auto'),
  language: 'auto',
  languageLabel: t('Auto'),
  profileRows: [],
  hasConnections: false,
  connectionRows: [],
  hasThresholds: false,
  thresholdRows: [],
  trainingBase: 'pace',
  trainingBaseLabel: t('Pace'),
  webUrl: WEB_URL,
  syncing: false,
  syncMessage: '',
  restoreScrollTop: 0,
};

function buildTrainingBaseOptions(active: string): TrainingBaseOption[] {
  const tr = buildSettingsTr();
  const map: { key: TrainingBaseOption['key']; label: string }[] = [
    { key: 'power', label: tr.trainingBasePower },
    { key: 'hr', label: tr.trainingBaseHr },
    { key: 'pace', label: tr.trainingBasePace },
  ];
  return map.map((m) => ({
    ...m,
    className:
      'settings-theme-option' +
      (m.key === active ? ' settings-theme-option--active' : ''),
  }));
}

function buildThemeOptions(active: ThemePref): ThemeOption[] {
  const themes: ThemePref[] = ['auto', 'dark', 'light'];
  return themes.map((th) => ({
    key: th,
    label: th === 'auto' ? t('Auto') : th === 'dark' ? t('Dark') : t('Light'),
    className:
      active === th
        ? 'settings-theme-opt settings-theme-opt--active'
        : 'settings-theme-opt',
  }));
}

function buildLanguageOptions(active: LanguagePref): LanguageOption[] {
  const langs: LanguagePref[] = ['auto', 'en', 'zh'];
  return langs.map((l) => ({
    key: l,
    // Language names render in their native script regardless of the
    // current UI locale — that's the universal convention so users can
    // identify their preferred tongue.
    label: l === 'auto' ? t('Auto') : l === 'en' ? 'English' : '中文',
    className:
      active === l
        ? 'settings-theme-opt settings-theme-opt--active'
        : 'settings-theme-opt',
  }));
}

function formatPlatform(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function formatThresholdDisplay(
  key: string,
  value: number | string | null,
  unit: string,
): string {
  if (value == null || value === '') return '—';
  if (unit === 'min/km' && typeof value === 'number') {
    const m = Math.floor(value / 60);
    const s = Math.round(value % 60);
    return `${m}:${String(s).padStart(2, '0')} /km`;
  }
  if (typeof value === 'number') {
    return `${Math.round(value)} ${unit}`.trim();
  }
  return `${value} ${unit}`.trim();
}

function buildSettingsState(response: SettingsResponse): Partial<SettingsState> {
  const { config, effective_thresholds } = response;
  const profileRows: ProfileRow[] = [
    { label: t('Name'), value: config.display_name || '—' },
    { label: t('Units'), value: config.unit_system },
    { label: t('Training base'), value: config.training_base },
  ];

  const connectionRows: ConnectionRow[] = config.connections.map((c) => ({
    key: c,
    label: formatPlatform(c),
  }));

  const thresholdRows: ThresholdRow[] = KNOWN_THRESHOLDS.map((k) => {
    const fromEffective = effective_thresholds?.[k];
    const rawConfig = config.thresholds?.[k];
    const value =
      fromEffective && fromEffective.value != null
        ? fromEffective.value
        : typeof rawConfig === 'number' || typeof rawConfig === 'string'
          ? rawConfig
          : null;
    const origin = fromEffective?.origin ?? 'none';
    const unit = THRESHOLD_UNIT[k] ?? '';
    return {
      key: k,
      label: THRESHOLD_LABEL[k] ?? k,
      display: formatThresholdDisplay(k, value, unit),
      hasOrigin: origin !== 'user' && origin !== 'none',
      origin: `from ${origin}`,
    };
  });

  const hasThresholds = thresholdRows.some((r) => r.display !== '—');

  const trainingBase = (config.training_base as 'power' | 'hr' | 'pace') ?? 'pace';
  return {
    loading: false,
    errorMessage: '',
    hasResponse: true,
    profileRows,
    hasConnections: connectionRows.length > 0,
    connectionRows,
    hasThresholds,
    thresholdRows,
    trainingBase,
    trainingBaseLabel: trainingBaseLabelFor(trainingBase),
  };
}

Page({
  data: { ...initialData, tr: buildSettingsTr() },

  onLoad() {
    const themePref = getThemePreference();
    const langPref = getLanguagePreference();
    // Restore scroll position if this load is the result of a reLaunch
    // triggered by a theme/language change from this page.
    const savedScroll = popSavedScroll();
    this.setData({
      themeClass: themeClassName(),
      theme: themePref,
      themeLabel: themeLabelFor(themePref),
      language: langPref,
      languageLabel: languageLabelFor(langPref),
      tr: buildSettingsTr(),
      restoreScrollTop: savedScroll,
    });
    void this.refetch();
  },

  onContentScroll(e: WechatMiniprogram.ScrollViewScroll) {
    // Track scroll position so we can save it before a reLaunch.
    // Written directly to the instance (not setData) to avoid re-render.
    (this as unknown as Record<string, number>)._scrollY = e.detail.scrollTop;
  },

  onShow() {
    applyThemeChrome();
    setTabBarSelected(this, 4);
  },

  onRetry() {
    void this.refetch();
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      const response = await apiGet<SettingsResponse>('/api/settings');
      this.setData(buildSettingsState(response) as Record<string, unknown>);
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') return;
      const detail = err?.detail ?? String(e);
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },

  async onPickLanguage() {
    const langKeys: LanguagePref[] = ['auto', 'en', 'zh'];
    wx.showActionSheet({
      itemList: [t('Auto'), 'English', '中文'],
      success: async (res) => {
        const next = langKeys[res.tapIndex];
        if (!next || next === this.data.language) return;
        setLanguagePreference(next);
        // Best-effort backend sync so the web app sees the same language.
        try {
          await apiPut('/api/settings', { language: next });
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('[settings] language backend sync failed:', err);
        }
        // Pages cache pre-translated tr objects — a reLaunch is required to
        // remount all pages so they re-evaluate their `buildXxxTr()` calls.
        // Navigate back to whichever tab/page the user was previously on so
        // the switch feels transparent rather than ejecting them to Settings.
        const url = relaunchUrl();
        saveScrollBefore((this as unknown as Record<string, number>)._scrollY ?? 0, url);
        wx.reLaunch({ url });
      },
    });
  },

  onPickTheme() {
    const themeKeys: ThemePref[] = ['auto', 'light', 'dark'];
    wx.showActionSheet({
      itemList: [t('Auto'), t('Light'), t('Dark')],
      success: (res) => {
        const next = themeKeys[res.tapIndex];
        if (!next || next === this.data.theme) return;
        setThemePreference(next);

        const newThemeClass = themeClassName();
        const newChartTheme: 'light' | 'dark' = newThemeClass === 'theme-light' ? 'light' : 'dark';

        // Update globalData — newly mounted pages read from here.
        getApp<IAppOption>().globalData.themeClass = newThemeClass;

        // Skyline: live-update all mounted pages without reLaunch.
        // No flash in Skyline (glass-easel renders the new theme
        // immediately without the WebView intermediate-frame artifact).
        const pages = getCurrentPages();
        for (const page of pages) {
          (page as WechatMiniprogram.Page.Instance<Record<string, unknown>, Record<string, unknown>>)
            .setData({ themeClass: newThemeClass, chartTheme: newChartTheme });
        }

        applyThemeChrome();

        this.setData({
          theme: next,
          themeLabel: themeLabelFor(next),
          themeClass: newThemeClass,
        });
      },
    });
  },

  onNavigateToScience() {
    wx.navigateTo({ url: '/pages/science/index' });
  },

  onCopyUrl() {
    wx.setClipboardData({ data: WEB_URL });
    wx.showToast({ title: 'URL copied', icon: 'success', duration: 1500 });
  },

  onSignOut() {
    clearToken();
    wx.reLaunch({ url: '/pages/login/index' });
  },

  /**
   * Persist a new training base via `PUT /api/settings`. The backend
   * recomputes thresholds + zones on the next page load, so we refetch
   * to pick up the cascaded effects (zone label set, threshold display
   * units, etc.). Race condition with another open client is fine —
   * server is the source of truth.
   */
  onPickTrainingBase() {
    const baseKeys: Array<'power' | 'hr' | 'pace'> = ['power', 'hr', 'pace'];
    const tr = this.data.tr as ReturnType<typeof buildSettingsTr>;
    wx.showActionSheet({
      itemList: [t('Power'), t('Heart rate'), t('Pace')],
      success: async (res) => {
        const next = baseKeys[res.tapIndex];
        if (!next || next === this.data.trainingBase) return;
        const previous = this.data.trainingBase as 'power' | 'hr' | 'pace';
        // Optimistic UI update so the row reflects the choice immediately.
        this.setData({
          trainingBase: next,
          trainingBaseLabel: trainingBaseLabelFor(next),
        });
        try {
          await apiPut('/api/settings', { training_base: next });
          void this.refetch();
        } catch (e2) {
          const err = e2 as Partial<ApiError>;
          if (err?.code === 'UNAUTHENTICATED') return;
          this.setData({
            trainingBase: previous,
            trainingBaseLabel: trainingBaseLabelFor(previous),
            errorMessage: err?.detail ?? tr.failedToLoad,
          });
        }
      },
    });
  },

  /**
   * Kick off a sync against every connected platform (`POST /api/sync`).
   * The backend runs the actual sync in a BackgroundTasks job and the
   * mini program just confirms the request was accepted — refreshing
   * Today / Training afterwards picks up the new data once the job
   * completes. This mirrors the web Sync All button.
   */
  async onSyncAll() {
    if (this.data.syncing) return;
    const tr = this.data.tr as ReturnType<typeof buildSettingsTr>;
    this.setData({ syncing: true, syncMessage: '' });
    try {
      await apiPost('/api/sync');
      this.setData({ syncing: false, syncMessage: tr.syncStarted });
      wx.showToast({ title: tr.syncStarted, icon: 'none', duration: 1800 });
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') return;
      this.setData({ syncing: false, syncMessage: err?.detail ?? tr.syncFailed });
    }
  },

  /**
   * Detach the current Praxys account from this WeChat profile so the user
   * can sign in as a different Praxys account, or test the first-run
   * onboarding flow without flashing the database. Calls the unlink
   * endpoint, clears the local JWT, then reLaunches to login — the next
   * `wx.login()` will return `needs_setup` and show the choose / link /
   * register UI.
   */
  onSwitchAccount() {
    wx.showModal({
      title: t('Switch Praxys account'),
      content: t(
        "This unlinks your WeChat profile from the current Praxys account. You'll be signed out and can sign in to a different account on next launch.",
      ),
      confirmText: t('Switch'),
      cancelText: t('Cancel'),
      success: (res) => {
        if (!res.confirm) return;
        void this.runSwitchAccount();
      },
    });
  },

  async runSwitchAccount() {
    const tr = this.data.tr as ReturnType<typeof buildSettingsTr>;
    wx.showLoading({ title: t('Unlinking…'), mask: true });
    let unlinkOk = false;
    let detail = '';
    try {
      await apiPost('/api/auth/wechat/unlink');
      unlinkOk = true;
    } catch (e) {
      const err = e as Partial<ApiError>;
      // 401 means the api-client is already redirecting to login. The
      // session is dead; treat this as success from the user's
      // perspective — they're being signed out anyway.
      if (err?.code === 'UNAUTHENTICATED') return;
      detail = err?.detail ?? String(e);
    } finally {
      wx.hideLoading();
    }

    if (!unlinkOk) {
      // Don't local-logout when the server still has the WeChat binding —
      // doing so leaves the user "signed out locally, bound on server",
      // which is exactly the bug the user reported. Surface a modal
      // explaining the failure and let them decide.
      wx.showModal({
        title: tr.switchAccount,
        content: detail ? `${tr.switchAccountFailed}\n\n(${detail})` : tr.switchAccountFailed,
        showCancel: false,
        confirmText: t('OK'),
      });
      return;
    }

    clearToken();
    wx.reLaunch({ url: '/pages/login/index' });
  },
});
