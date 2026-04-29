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
export function setTabBarSelected(
  page: { getTabBar?: unknown },
  selected: number,
): void {
  if (typeof page.getTabBar !== 'function') return;

  // Skyline: getTabBar(callback) — async
  // WebView: getTabBar() returns instance — sync
  // We try calling with a callback. In WebView the function signature
  // ignores the argument and returns the instance; we handle that fallback.
  try {
    const result = (page.getTabBar as Function)(
      (tabBar: { setData: (d: Record<string, unknown>) => void } | null) => {
        // Skyline callback path
        tabBar?.setData({ selected });
      },
    );
    // WebView sync path: getTabBar() returned the instance directly
    if (result && typeof (result as { setData?: unknown }).setData === 'function') {
      (result as { setData: (d: Record<string, unknown>) => void }).setData({ selected });
    }
  } catch {
    // ignore — tab bar not available on this page (e.g. sub-pages)
  }
}
