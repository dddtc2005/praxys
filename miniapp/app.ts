import { themeClassName, getThemePreference } from './utils/theme';

/**
 * Shape of getApp<IAppOption>().globalData.
 */
export interface IAppOption {
  globalData: {
    /** Resolved theme class ('theme-dark' | 'theme-light'). Set in onLaunch
     *  and refreshed on theme changes so pages read the correct value at
     *  module-load time without a storage round-trip. */
    themeClass: string;
  };
}

App<IAppOption>({
  globalData: {
    themeClass: 'theme-light', // overwritten in onLaunch before any page mounts
  },

  onLaunch() {
    const tc = themeClassName();
    this.globalData.themeClass = tc;

    // Sync window chrome background to the user's preference. The CSS
    // @media prefers-color-scheme already handles the system-auto case
    // at parse time; this call covers manual overrides (user forced Dark
    // while system is Light, or vice versa).
    const bg = tc === 'theme-light' ? '#faf9f5' : '#0d1220';
    wx.setBackgroundColor({ backgroundColor: bg, fail: () => {} });

    // React to system theme changes when the user's preference is "Auto".
    // When the system switches dark/light, update globalData and the chrome
    // so pages that come to foreground after the switch render correctly.
    wx.onThemeChange?.((res) => {
      if (getThemePreference() !== 'auto') return; // user has manual override
      const newTc = res.theme === 'dark' ? 'theme-dark' : 'theme-light';
      this.globalData.themeClass = newTc;
      const newBg = newTc === 'theme-light' ? '#faf9f5' : '#0d1220';
      wx.setBackgroundColor({ backgroundColor: newBg, fail: () => {} });
    });
  },
});
