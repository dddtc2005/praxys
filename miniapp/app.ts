import { themeClassName } from './utils/theme';

/**
 * Shape of getApp<IAppOption>().globalData. Typed so every page can
 * read the resolved theme at module-load time without making its own
 * storage call, eliminating the one-frame light-theme flash on dark
 * devices (the "first-paint flash" bug).
 *
 * Only `themeClass` lives here — per-user data (JWT, prefs) belongs in
 * wx.storage, not in-memory app state, so it survives WeChat's mini-
 * program suspend/resume lifecycle.
 */
export interface IAppOption {
  globalData: {
    /** Resolved theme class, e.g. 'theme-dark' | 'theme-light'. Set
     *  once in onLaunch and refreshed on every theme change from
     *  Settings, so any page reading it at module-load time gets the
     *  correct value immediately. */
    themeClass: string;
  };
}

App<IAppOption>({
  globalData: {
    themeClass: 'theme-light', // overwritten in onLaunch before any page mounts
  },

  onLaunch() {
    // Resolve theme once at startup and cache on globalData so every page's
    // initialData reads the correct class without a storage round-trip.
    const tc = themeClassName();
    this.globalData.themeClass = tc;

    // Set the window chrome background IMMEDIATELY at launch — before any
    // page renders — so the static #0d1220 default in app.json / page CSS
    // is updated to the actual user preference on first paint. Without this
    // call, light-mode users would briefly see the dark default.
    const bg = tc === 'theme-light' ? '#faf9f5' : '#0d1220';
    wx.setBackgroundColor({ backgroundColor: bg, fail: () => {} });
  },
});
