import { themeClassName } from './utils/theme';

/**
 * Shape of the app instance shared across pages via `getApp<IAppOption>()`.
 * Exported so pages can type their `getApp()` call and read globalData
 * without an `as` cast.
 */
export interface IAppOption {
  globalData: {
    /**
     * Resolved theme class (`'theme-light'` or `'theme-dark'`) computed
     * once in onLaunch. Pages read this at module load to set their
     * initial `data.themeClass` so first-paint matches the user's
     * preference instead of briefly rendering the light-default and
     * then snapping to dark on first setData.
     *
     * Theme *changes* still go through wx.reLaunch (see Settings page),
     * which re-runs onLaunch and rebuilds globalData from scratch.
     */
    themeClass: string;
  };
}

// Root app lifecycle. The login page owns the auth flow on its own
// onLoad, so onLaunch only resolves the user's theme preference into
// globalData — keeping startup deterministic regardless of which page
// the user lands on.
App<IAppOption>({
  globalData: {
    themeClass: 'theme-light',
  },
  onLaunch() {
    this.globalData.themeClass = themeClassName();
  },
});
