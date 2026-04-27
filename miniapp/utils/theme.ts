/**
 * Theme handling for the mini program.
 *
 * Three user-visible options:
 *   'auto'  - follow the WeChat client's theme (dark if phone is in dark mode)
 *   'dark'  - force dark
 *   'light' - force light
 *
 * The resolved theme ('dark' | 'light') gets applied as a class on each
 * page's root <view>. All WXSS colour values live in CSS variables defined
 * in app.scss; the two classes just re-assign them.
 *
 * Mini programs don't share a DOM across pages the way a web SPA does, so
 * each page reads the preference on mount and sets its own root className.
 * When the user changes the preference we wx.reLaunch — crude but reliable
 * across every page in one shot.
 *
 * Under Skyline + custom navigation the native nav bar is hidden, so
 * setNavigationBarColor is no longer called — the per-page custom <nav-bar>
 * component owns the chrome. setTabBarStyle is unaffected by Skyline and
 * still works for tab-bar pages.
 */

export type ThemePref = 'auto' | 'dark' | 'light';
export type ResolvedTheme = 'dark' | 'light';

const THEME_STORAGE_KEY = 'praxys-theme';

export function getThemePreference(): ThemePref {
  const stored = wx.getStorageSync<ThemePref | string>(THEME_STORAGE_KEY);
  if (stored === 'dark' || stored === 'light' || stored === 'auto') return stored;
  return 'auto';
}

export function setThemePreference(theme: ThemePref): void {
  wx.setStorageSync(THEME_STORAGE_KEY, theme);
}

/**
 * Returns the concrete theme to render. For 'auto', reads the WeChat
 * client's current theme: 'dark' only when the client reports dark,
 * 'light' otherwise (including the case where the API throws or returns
 * an unexpected value). Light is the Praxys default — see web/index.html's
 * first-paint script, the authoritative source.
 *
 * Native unblocks wx.getAppBaseInfo() (libVersion 2.20.1+) which is the
 * modern replacement for getSystemInfoSync. Taro's runtime proxy didn't
 * forward it.
 */
export function resolveTheme(pref: ThemePref = getThemePreference()): ResolvedTheme {
  if (pref === 'dark' || pref === 'light') return pref;
  try {
    const info: { theme?: string } =
      typeof wx.getAppBaseInfo === 'function'
        ? wx.getAppBaseInfo()
        : (wx.getSystemInfoSync() as unknown as { theme?: string });
    if (info.theme === 'dark') return 'dark';
    return 'light';
  } catch {
    return 'light';
  }
}

/** Shorthand: return the className every page should apply to its root view. */
export function themeClassName(): string {
  return `theme-${resolveTheme()}`;
}

/**
 * Colours used by the canvas renderer. Canvas drawing happens in
 * JavaScript, not WXSS, so it can't read CSS variables — keep this in
 * sync with app.scss by construction.
 */
export interface ChartColors {
  axis: string;
  grid: string;
  tick: string;
  zero: string;
}

const DARK_CHART: ChartColors = {
  axis: '#1f2536',
  grid: '#161b2e',
  tick: '#8b93a7',
  zero: '#00ff87',
};

const LIGHT_CHART: ChartColors = {
  axis: '#dbd6c7',
  grid: '#edeae0',
  tick: '#6b6b66',
  zero: '#1e8e5b',
};

export function chartColors(theme: ResolvedTheme = resolveTheme()): ChartColors {
  return theme === 'light' ? LIGHT_CHART : DARK_CHART;
}

/**
 * Repaint WeChat's tab bar to match the active theme. Status bar / nav
 * bar are owned by the per-page custom nav component under Skyline, so
 * we no longer call setNavigationBarColor here.
 *
 * Call from every tab-bar page's onShow (the first page to run after the
 * user switches theme determines the chrome state for subsequent tabs).
 */
export function applyThemeChrome(theme: ResolvedTheme = resolveTheme()): void {
  const isLight = theme === 'light';
  const bg = isLight ? '#faf9f5' : '#0d1220';
  const selected = isLight ? '#1e8e5b' : '#00ff87';
  const muted = isLight ? '#6b6b66' : '#8b93a7';

  wx.setTabBarStyle({
    backgroundColor: bg,
    color: muted,
    selectedColor: selected,
    borderStyle: isLight ? 'white' : 'black',
    fail: () => {
      // setTabBarStyle fails on pages that aren't registered as tab-bar
      // pages (e.g. login, science). That's expected — nothing to do.
    },
  });
}
