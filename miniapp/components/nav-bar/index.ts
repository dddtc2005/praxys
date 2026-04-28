/**
 * Custom navigation bar for Skyline pages.
 *
 * Skyline pages have `navigationStyle: custom`, which hides the native
 * top bar entirely. This component fills that gap with brand-styled
 * chrome that vertically aligns with WeChat's capsule (the menu/close
 * buttons floating in the top-right). Without that alignment the title
 * looks crooked relative to the capsule.
 *
 * Sizing math:
 *   - statusBarHeight = full system status bar (20-44 px depending on device)
 *   - menuRect.top   = where the WeChat capsule starts
 *   - The padding above and below the capsule should be equal:
 *       padTopBottom = menuRect.top - statusBarHeight
 *   - Content height = menuRect.height + 2 * padTopBottom
 *   - Total height   = statusBarHeight + contentHeight
 */

Component({
  options: {
    addGlobalClass: true,
  },

  properties: {
    title: { type: String as StringConstructor, value: '' },
    showBack: { type: Boolean as BooleanConstructor, value: false },
    themeClass: { type: String as StringConstructor, value: 'theme-light' },
    /** Show /PRAXYS wordmark instead of title — used by tab pages so the
     *  brand identity is on every screen. Sub-pages keep title. */
    showWordmark: { type: Boolean as BooleanConstructor, value: false },
    /** Right-slot action label (e.g. "Edit"). Tap fires `rightaction`
     *  event so the parent page can react. Ignored when rightShare=true. */
    rightText: { type: String as StringConstructor, value: '' },
    /** Render the right slot as a native share button. Tap is handled by
     *  WeChat (calls the page's onShareAppMessage); the parent does NOT
     *  receive a `rightaction` event in this mode. */
    rightShare: { type: Boolean as BooleanConstructor, value: false },
  },

  data: {
    statusBarHeight: 20,
    contentHeight: 44,
    totalHeight: 64,
    capsuleReservedPx: 100,
  },

  lifetimes: {
    attached() {
      this.computeLayout();
    },
  },

  methods: {
    computeLayout() {
      try {
        const win: { statusBarHeight?: number; windowWidth: number } =
          typeof wx.getWindowInfo === 'function' ? wx.getWindowInfo() : wx.getSystemInfoSync();
        const menu = wx.getMenuButtonBoundingClientRect();
        const statusBarHeight = win.statusBarHeight || 20;
        const padTopBottom = Math.max(0, menu.top - statusBarHeight);
        const contentHeight = menu.height + padTopBottom * 2;
        const totalHeight = statusBarHeight + contentHeight;
        const capsuleReservedPx = Math.max(0, win.windowWidth - menu.left + 12);
        this.setData({ statusBarHeight, contentHeight, totalHeight, capsuleReservedPx });
      } catch {
        // Older clients without getMenuButtonBoundingClientRect: fall back
        // to a fixed 64px nav bar with conservative right-side reserve.
        this.setData({ statusBarHeight: 20, contentHeight: 44, totalHeight: 64, capsuleReservedPx: 100 });
      }
    },

    onBackTap() {
      const pages = getCurrentPages();
      if (pages.length > 1) {
        wx.navigateBack({ delta: 1 });
      } else {
        wx.reLaunch({ url: '/pages/today/index' });
      }
    },

    onRightTap() {
      // Bubble out so the parent page's `bindrightaction` handler runs.
      // We don't pass any detail — pages know their own context (e.g.
      // Goal page interprets this as "open editor").
      this.triggerEvent('rightaction');
    },
  },
});
