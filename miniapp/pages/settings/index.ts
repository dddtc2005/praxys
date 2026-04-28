import { apiGet, apiPost } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import { clearToken } from '../../utils/auth';
import {
  applyThemeChrome,
  getThemePreference,
  setThemePreference,
  themeClassName,
} from '../../utils/theme';
import type { ThemePref } from '../../utils/theme';
import { getLanguagePreference, setLanguagePreference } from '../../utils/share';
import { t } from '../../utils/i18n';
import type { SettingsResponse } from '../../types/api';

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
    themeHint: t('Auto follows your WeChat system theme. Changing this reloads the app.'),
    language: t('Language'),
    languageAuto: t('Auto'),
    languageHint: t(
      'Affects share copy now; full UI translation is web-only for the moment.',
    ),
    openOnWeb: t('Open Praxys on web'),
    signOut: t('Log out'),
    switchAccount: t('Switch Praxys account'),
    switchAccountHint: t(
      'Unbind your WeChat profile from this Praxys account so you can sign in as someone else or test the first-time onboarding flow.',
    ),
    connected: t('Connected'),
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
  themeOptions: ThemeOption[];
  language: LanguagePref;
  languageOptions: LanguageOption[];

  profileRows: ProfileRow[];
  hasConnections: boolean;
  connectionRows: ConnectionRow[];

  hasThresholds: boolean;
  thresholdRows: ThresholdRow[];

  webUrl: string;
}

const initialData: SettingsState = {
  themeClass: 'theme-light',
  loading: true,
  errorMessage: '',
  hasResponse: false,
  theme: 'auto',
  themeOptions: [],
  language: 'auto',
  languageOptions: [],
  profileRows: [],
  hasConnections: false,
  connectionRows: [],
  hasThresholds: false,
  thresholdRows: [],
  webUrl: WEB_URL,
};

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

  return {
    loading: false,
    errorMessage: '',
    hasResponse: true,
    profileRows,
    hasConnections: connectionRows.length > 0,
    connectionRows,
    hasThresholds,
    thresholdRows,
  };
}

Page({
  data: { ...initialData, tr: buildSettingsTr() },

  onLoad() {
    const themePref = getThemePreference();
    const langPref = getLanguagePreference();
    this.setData({
      themeClass: themeClassName(),
      theme: themePref,
      themeOptions: buildThemeOptions(themePref),
      language: langPref,
      languageOptions: buildLanguageOptions(langPref),
    });
    void this.refetch();
  },

  onShow() {
    applyThemeChrome();
    const tabBar = (this as { getTabBar?: () => { setData: (d: unknown) => void } | null })
      .getTabBar?.();
    tabBar?.setData({ selected: 4 });
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

  onPickLanguage(e: WechatMiniprogram.TouchEvent) {
    const next = e.currentTarget.dataset.lang as LanguagePref;
    if (!next || next === this.data.language) return;
    setLanguagePreference(next);
    // Pages cache pre-translated strings on their data — a setData on
    // the tab bar isn't enough. reLaunch back to settings forces every
    // page (and the tab bar) to remount and re-pull the new locale,
    // mirroring the theme switch flow.
    wx.reLaunch({ url: '/pages/settings/index' });
  },

  onPickTheme(e: WechatMiniprogram.TouchEvent) {
    const next = e.currentTarget.dataset.theme as ThemePref;
    if (!next || next === this.data.theme) return;
    setThemePreference(next);
    // Mini programs don't share a DOM across pages — every page already
    // read the old preference during its mount. wx.reLaunch is the
    // cleanest way to force every page to re-evaluate themeClassName()
    // and pick up new colours. Re-launch back to settings (not today)
    // so the user stays on this page after the swap.
    wx.reLaunch({ url: '/pages/settings/index' });
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
    wx.showLoading({ title: t('Unlinking…'), mask: true });
    try {
      await apiPost('/api/auth/wechat/unlink');
    } catch (e) {
      // If the unlink fails we still proceed locally — the user wanted
      // out. Worst case, the next sign-in returns 'ok' for the same
      // account, and they can try Switch again. Toast the error so the
      // failure isn't completely silent.
      const detail = (e as Partial<ApiError>)?.detail ?? String(e);
      // eslint-disable-next-line no-console
      console.warn('[settings] wechat unlink failed:', detail);
    } finally {
      wx.hideLoading();
    }
    clearToken();
    wx.reLaunch({ url: '/pages/login/index' });
  },
});
