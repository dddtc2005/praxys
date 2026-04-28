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

import { t } from '../utils/i18n';

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

const TABS: TabConfig[] = buildTabs();

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
    tabs: TABS,
    selected: 0,
    themeClass: 'theme-light',
  },

  lifetimes: {
    // First paint when the Component instance is created (per-page).
    // Read theme + locale here so the bar renders correctly without
    // waiting for the first pageLifetimes.show.
    attached() {
      this.setData({
        tabs: buildTabs(),
        themeClass: `theme-${resolveCurrentTheme()}`,
      });
    },
  },

  pageLifetimes: {
    show() {
      // Refresh on every tab-page show — covers Language switch
      // (reLaunch) and Theme switch (reLaunch). We always setData on
      // both fields, even when the value matches, so a real-device
      // glitch where the previous setData didn't paint gets a second
      // chance. The cost is one extra render per page-show, which is
      // imperceptible on a 5-item tab bar.
      const themeClass = `theme-${resolveCurrentTheme()}`;
      this.setData({ tabs: buildTabs(), themeClass });

      // Snap selected index to whichever tab page is currently active.
      const pages = getCurrentPages();
      const top = pages[pages.length - 1];
      if (!top) return;
      const idx = TABS.findIndex((tab) => tab.pagePath === top.route);
      if (idx >= 0 && idx !== this.data.selected) {
        this.setData({ selected: idx });
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
