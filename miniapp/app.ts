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
    // Resolve the user's theme preference once at app start and cache it
    // on globalData. Pages read globalData.themeClass in initialData so
    // their first render is already in the right theme.
    this.globalData.themeClass = themeClassName();
  },
});
