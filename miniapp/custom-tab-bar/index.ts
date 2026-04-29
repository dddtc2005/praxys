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
    // Read from globalData (set in app.ts onLaunch) so the first render
    // already has the correct theme — not a hardcoded light fallback.
    themeClass: getApp<IAppOption>().globalData.themeClass,
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
      // Guard every field with an equality check so we only call setData
      // when something actually changed. Unconditional setData on every
      // tab switch was the root cause of the intermittent white flash:
      // multiple overlapping re-renders from rapidly-switched tabs
      // created a race condition in glass-easel's paint queue.
      //
      // Language and theme both use wx.reLaunch, so after any change
      // all pages reload fresh. Rebuilding tabs[] here is unnecessary
      // (it's done once in attached()). We only update themeClass (for
      // the system-theme-change edge case) and selected.
      const updates: Record<string, unknown> = {};

      const themeClass = `theme-${resolveCurrentTheme()}`;
      if (themeClass !== this.data.themeClass) {
        updates.themeClass = themeClass;
      }

      const pages = getCurrentPages();
      const top = pages[pages.length - 1];
      if (top) {
        const idx = TABS.findIndex((tab) => tab.pagePath === top.route);
        if (idx >= 0 && idx !== this.data.selected) {
          updates.selected = idx;
        }
      }

      // One setData call (or none) per tab switch — not two.
      if (Object.keys(updates).length > 0) {
        this.setData(updates);
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
