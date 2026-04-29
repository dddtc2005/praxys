/**
 * Set the custom tab bar's selected index in a way that works in
 * both WebView (sync getTabBar) and Skyline (async callback getTabBar).
 *
 * WeChat documentation on custom tab bar in Skyline:
 *   https://developers.weixin.qq.com/miniprogram/dev/framework/ability/custom-tabbar.html
 *
 * In Skyline, getTabBar() MUST be called with a callback — calling it
 * synchronously returns undefined (silently fails). In WebView the
 * sync form works. This shim tries the callback form first (Skyline)
 * and falls back to the sync form (WebView).
 */
type TabBarInstance = { setData: (d: Record<string, unknown>) => void };

/**
 * Call setData on the custom tab bar Component in a way that works in
 * both Skyline (async getTabBar callback) and WebView (sync return).
 */
function callTabBar(
  page: { getTabBar?: unknown },
  data: Record<string, unknown>,
): void {
  if (typeof page.getTabBar !== 'function') return;
  try {
    const result = (page.getTabBar as Function)(
      (tabBar: TabBarInstance | null) => {
        tabBar?.setData(data);
      },
    );
    // WebView sync fallback: getTabBar() returned the instance
    if (result && typeof (result as { setData?: unknown }).setData === 'function') {
      (result as TabBarInstance).setData(data);
    }
  } catch {
    // not available on sub-pages (science, login, etc.)
  }
}

export function setTabBarSelected(
  page: { getTabBar?: unknown },
  selected: number,
): void {
  callTabBar(page, { selected });
}

export function setTabBarTheme(
  page: { getTabBar?: unknown },
  themeClass: string,
): void {
  callTabBar(page, { themeClass });
}

/** Rebuild tab bar labels after a live language change. */
export function refreshTabBarLocale(page: { getTabBar?: unknown }): void {
  // Mirrors custom-tab-bar/index.ts buildTabs(). Inline the i18n import
  // to avoid pulling the whole catalog into this tiny shim module.
  import('./i18n').then(({ t }) => {
    const tabs = [
      { pagePath: 'pages/today/index', text: t('Today'), kind: 'today' },
      { pagePath: 'pages/training/index', text: t('Training'), kind: 'training' },
      { pagePath: 'pages/history/index', text: t('Activities'), kind: 'activities' },
      { pagePath: 'pages/goal/index', text: t('Goal'), kind: 'goal' },
      { pagePath: 'pages/settings/index', text: t('Settings'), kind: 'settings' },
    ];
    callTabBar(page, { tabs });
  }).catch(() => { /* tab labels will refresh on next pageLifetimes.show */ });
}
