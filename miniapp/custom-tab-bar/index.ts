/**
 * Custom tab bar — auto-loaded by WeChat when `tabBar.custom: true`
 * is set in app.json. Lives at the project root in `custom-tab-bar/`
 * (the path is hard-coded by the platform).
 *
 * We render brand-styled CSS-drawn icons (no PNG asset pipeline) and
 * sync the active state by reading `getCurrentPages()` in
 * `pageLifetimes.show` — this avoids per-page wiring.
 *
 * The 5 pages (Today / Training / Activities / Goal / Settings) match
 * `tabBar.list` in app.json. `kind` is the icon discriminator; SCSS
 * draws the right shape per kind.
 */

import { t, detectLocale } from '../utils/i18n';
import type { IAppOption } from '../app';

interface TabConfig {
  pagePath: string;
  text: string;
  kind: 'today' | 'training' | 'activities' | 'goal' | 'settings';
}

// Built lazily so tab labels reflect the *current* language preference,
// not the value at module-load time. We rebuild on every page show to
// pick up changes made in Settings → Language.
function buildTabs(): TabConfig[] {
  return [
    { pagePath: 'pages/today/index', text: t('Today'), kind: 'today' },
    { pagePath: 'pages/training/index', text: t('Training'), kind: 'training' },
    { pagePath: 'pages/history/index', text: t('Activities'), kind: 'activities' },
    { pagePath: 'pages/goal/index', text: t('Goal'), kind: 'goal' },
    { pagePath: 'pages/settings/index', text: t('Settings'), kind: 'settings' },
  ];
}

function resolveCurrentTheme(): 'dark' | 'light' {
  const stored = wx.getStorageSync<string>('praxys-theme') || 'auto';
  if (stored === 'dark') return 'dark';
  if (stored === 'light') return 'light';
  try {
    const info =
      typeof wx.getAppBaseInfo === 'function'
        ? wx.getAppBaseInfo()
        : (wx.getSystemInfoSync() as unknown as { theme?: string });
    if (info.theme === 'dark') return 'dark';
  } catch {
    /* fall back to light */
  }
  return 'light';
}

Component({
  options: { addGlobalClass: true },

  data: {
    tabs: buildTabs(),
    selected: 0,
    themeClass: getApp<IAppOption>().globalData.themeClass,
    // Cached locale; used as a drift guard in pageLifetimes.show so we
    // only rebuild tabs when the language actually changed (otherwise
    // every tab switch would re-render the bar).
    _locale: '' as string,
  },

  lifetimes: {
    // First paint when the Component instance is created (per-page).
    // Read theme + locale here so the bar renders correctly without
    // waiting for the first pageLifetimes.show.
    attached() {
      this.setData({
        tabs: buildTabs(),
        themeClass: `theme-${resolveCurrentTheme()}`,
        _locale: detectLocale(),
      });
    },
  },

  pageLifetimes: {
    show() {
      // Each tab-bar page's onShow directly calls tabBar.setData({ selected })
      // so we don't need to derive it here from getCurrentPages() (which can
      // be stale during rapid tab switching).
      const themeClass = `theme-${resolveCurrentTheme()}`;
      if (themeClass !== this.data.themeClass) {
        this.setData({ themeClass });
      }
      // Locale drift: when the user switches language on the Settings
      // tab, only Settings's tab-bar Component instance is refreshed via
      // refreshTabBarLocale(). Other tab pages' tab-bar instances retain
      // stale labels until they're re-attached. Catch the drift here so
      // the bar updates the next time the user navigates to a new tab.
      const locale = detectLocale();
      if (locale !== this.data._locale) {
        this.setData({ tabs: buildTabs(), _locale: locale });
      }
    },
  },

  methods: {
    switchTab(e: WechatMiniprogram.TouchEvent) {
      const path = e.currentTarget.dataset.path as string | undefined;
      if (!path) return;
      wx.switchTab({ url: `/${path}` });
    },
  },
});
