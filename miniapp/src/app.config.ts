/**
 * Mini-program-level configuration: page registry, tab bar, window style.
 * Changes here require a rebuild and a reload in WeChat DevTools.
 */
export default defineAppConfig({
  pages: [
    // The first entry is the launch page. The login page runs `Taro.login` on
    // mount, exchanges the code for either a JWT or a setup ticket, and then
    // either redirects to today/index or shows the onboarding step.
    'pages/login/index',
    'pages/today/index',
    'pages/training/index',
    'pages/goal/index',
    'pages/history/index',
    'pages/settings/index',
    'pages/science/index',
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#faf9f5',
    navigationBarTitleText: 'Praxys',
    navigationBarTextStyle: 'black',
    backgroundColor: '#faf9f5',
  },
  tabBar: {
    color: '#6b6b66',
    selectedColor: '#1e8e5b',
    backgroundColor: '#faf9f5',
    borderStyle: 'white',
    list: [
      { pagePath: 'pages/today/index', text: 'Today' },
      { pagePath: 'pages/training/index', text: 'Training' },
      { pagePath: 'pages/history/index', text: 'Activities' },
      { pagePath: 'pages/goal/index', text: 'Goal' },
      { pagePath: 'pages/settings/index', text: 'Settings' },
    ],
  },
  // Request/socket/download domains must match the WeChat console whitelist in
  // production; the simulator can bypass this via 开发-不校验合法域名.
});
