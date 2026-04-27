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
    { pagePath: 'pages/goal/index', text: t('Goal Tracker'), kind: 'goal' },
    { pagePath: 'pages/settings/index', text: t('Settings'), kind: 'settings' },
  ];
}

const TABS: TabConfig[] = buildTabs();

Component({
  options: { addGlobalClass: true },

  data: {
    tabs: TABS,
    selected: 0,
    themeClass: 'theme-light',
  },

  pageLifetimes: {
    show() {
      // Refresh tab labels in case the user just changed Language. This
      // is the cheapest safe place — every tab page's onShow runs the
      // component's pageLifetimes.show.
      this.setData({ tabs: buildTabs() });

      // Snap selected index to whichever tab page is currently active.
      // Runs every time a tab page comes to foreground — covers initial
      // launch, tab switches, and pop-from-sub-page.
      const pages = getCurrentPages();
      const top = pages[pages.length - 1];
      if (!top) return;
      const idx = TABS.findIndex((tab) => tab.pagePath === top.route);
      if (idx >= 0 && idx !== this.data.selected) {
        this.setData({ selected: idx });
      }
      // Also pull the current theme so the bar repaints when the user
      // switches Light/Dark from Settings.
      const stored = wx.getStorageSync<string>('praxys-theme') || 'auto';
      let resolved: 'dark' | 'light' = 'light';
      if (stored === 'dark') resolved = 'dark';
      else if (stored === 'auto') {
        try {
          const info =
            typeof wx.getAppBaseInfo === 'function'
              ? wx.getAppBaseInfo()
              : (wx.getSystemInfoSync() as unknown as { theme?: string });
          if (info.theme === 'dark') resolved = 'dark';
        } catch {
          /* fall back to light */
        }
      }
      const themeClass = `theme-${resolved}`;
      if (themeClass !== this.data.themeClass) this.setData({ themeClass });
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
