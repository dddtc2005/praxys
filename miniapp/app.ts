import { themeClassName, getThemePreference } from './utils/theme';
import { detectLocale } from './utils/i18n';

/**
 * Shape of getApp<IAppOption>().globalData.
 */
export interface IAppOption {
  globalData: {
    /** Resolved theme class ('theme-dark' | 'theme-light'). */
    themeClass: string;
    /** Active locale ('en' | 'zh'). Updated on language change so pages
     *  can detect drift without a storage read in their onShow guard. */
    locale: string;
  };
}

App<IAppOption>({
  globalData: {
    themeClass: 'theme-light',
    locale: 'zh',
  },

  onLaunch() {
    const tc = themeClassName();
    this.globalData.themeClass = tc;
    this.globalData.locale = detectLocale();

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
