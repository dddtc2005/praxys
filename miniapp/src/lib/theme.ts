import Taro from '@tarojs/taro';

/**
 * Theme handling for the mini program.
 *
 * There are three user-visible options:
 *   'auto' - follow the WeChat client's theme (dark if phone is in dark mode)
 *   'dark' - force dark
 *   'light' - force light
 *
 * The resolved theme ('dark' | 'light') gets applied as a class on each
 * page's root View. All SCSS colour values live in CSS variables defined
 * in app.scss; the two classes just re-assign them.
 *
 * Mini programs don't share a DOM across pages the way a web SPA does, so
 * there's no single "root" to set the class on once. Each page reads the
 * preference on mount and sets its own root className. When the user
 * changes the preference we Taro.reLaunch — crude but reliable across
 * every page in one shot.
 */

export type ThemePref = 'auto' | 'dark' | 'light';
export type ResolvedTheme = 'dark' | 'light';

const THEME_STORAGE_KEY = 'praxys-theme';

export function getThemePreference(): ThemePref {
  const stored = Taro.getStorageSync(THEME_STORAGE_KEY);
  if (stored === 'dark' || stored === 'light' || stored === 'auto') return stored;
  return 'auto';
}

export function setThemePreference(theme: ThemePref): void {
  Taro.setStorageSync(THEME_STORAGE_KEY, theme);
}

/**
 * Returns the concrete theme to render. For 'auto', reads the WeChat
 * client's current theme.
 *
 * Uses getSystemInfoSync despite the deprecation warning because Taro
 * 4.2.0's runtime wrapper only forwards getSystemInfoSync — the newer
 * scoped replacements (getAppBaseInfo / getWindowInfo) are declared in
 * Taro's .d.ts but are undefined at runtime, so calling them throws.
 * Revisit when Taro adds them to the runtime proxy.
 */
export function resolveTheme(pref: ThemePref = getThemePreference()): ResolvedTheme {
  if (pref === 'dark' || pref === 'light') return pref;
  try {
    const info = Taro.getSystemInfoSync() as { theme?: string };
    if (info.theme === 'light') return 'light';
    return 'dark';
  } catch {
    return 'dark';
  }
}

/** Shorthand: return the className every page should apply to its root View. */
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
 * Repaints WeChat's native chrome (status bar + tab bar) to match the
 * active theme. These surfaces are NOT reachable from CSS — they're
 * configured statically in app.config.ts and only mutable at runtime
 * through Taro.setNavigationBarColor / Taro.setTabBarStyle.
 *
 * Call from every page's useDidShow (the first page to run after the
 * user switches theme determines the chrome state for subsequent tabs).
 */
export function applyThemeChrome(theme: ResolvedTheme = resolveTheme()): void {
  // Keep in sync with app.scss theme tokens. Values are hex
  // approximations of the OKLCH definitions in web/src/index.css.
  const isLight = theme === 'light';
  const bg = isLight ? '#faf9f5' : '#0d1220';
  const selected = isLight ? '#1e8e5b' : '#00ff87';
  const muted = isLight ? '#6b6b66' : '#8b93a7';
  const frontColor = isLight ? '#000000' : '#ffffff';

  Taro.setNavigationBarColor({
    frontColor,
    backgroundColor: bg,
  }).catch(() => {
    // Some pages (the launch screen) can't change the nav colour until
    // after first render; silent-ignore those races.
  });

  Taro.setTabBarStyle({
    backgroundColor: bg,
    color: muted,
    selectedColor: selected,
    borderStyle: isLight ? 'white' : 'black',
  }).catch(() => {
    // setTabBarStyle fails on pages that aren't registered as tab-bar
    // pages (e.g. login, science). That's expected — nothing to do.
  });
}
