/**
 * Mini-program-local translation extras.
 *
 * The auto-synced `i18n-catalog.ts` only contains keys that web's source
 * tree marks for translation via lingui (`<Trans>` / `t\`...\``). Strings
 * unique to the mini program — login copy, switch-account modal,
 * tap-to-copy-URL hints, etc. — never get extracted on the web side and
 * therefore have no translations even though they're called via `t()`.
 *
 * Rather than hack the web catalog (which lingui-extract would clobber
 * on the next run) or hardcode locale switches throughout, we put them
 * here. `t()` in `i18n.ts` checks this map first, then falls through to
 * the auto-synced catalog, then falls back to the English key. So
 * lingui-driven strings stay single-sourced in web/, and mini-only
 * strings stay single-sourced here.
 *
 * Add a key only when:
 *   1. The string is genuinely mini-program-only (no equivalent on web)
 *   2. The key isn't already in `web/src/locales/zh/messages.po`
 *
 * Otherwise add the string to web's <Trans> usage and let the i18n
 * workflow translate it on the next run.
 */
import type { Locale } from './i18n-catalog';

export const I18N_EXTRA: Record<Locale, Record<string, string>> = {
  en: {
    // English keys map to themselves — we only really need this map for
    // the override semantics, but listing them keeps the typing
    // symmetric and makes it obvious when a key was intentionally added
    // here rather than pulled from web.
    'Train like a pro. Whatever your level.': 'Train like a pro. Whatever your level.',
    'Sign in with WeChat': 'Sign in with WeChat',
    'Signing you in…': 'Signing you in…',
    'Sign-in failed': 'Sign-in failed',
    'Sign-in code unavailable. Please try again.':
      'Sign-in code unavailable. Please try again.',
    'WeChat sign-in is not configured on this server.':
      'WeChat sign-in is not configured on this server.',
    'Your session expired. Please sign in again.':
      'Your session expired. Please sign in again.',
    'Sign in to Praxys': 'Sign in to Praxys',
    'Link to Praxys': 'Link to Praxys',
    email: 'email',
    password: 'password',
    'Email and password are required': 'Email and password are required',
    'New here? Sign up at': 'New here? Sign up at',
    'tap to copy URL': 'tap to copy URL',
    'URL copied': 'URL copied',
    Retry: 'Retry',
    OK: 'OK',
    Switch: 'Switch',
    Cancel: 'Cancel',
    'Switch Praxys account': 'Switch Praxys account',
    'Unlinking…': 'Unlinking…',
    Sync: 'Sync',
    'Sync now': 'Sync now',
    'Syncing…': 'Syncing…',
    'Sync started in the background.': 'Sync started in the background.',
    'Sync request failed. Try again from the web app if it persists.':
      'Sync request failed. Try again from the web app if it persists.',
    'Use this': 'Use this',
    'Failed to switch theory': 'Failed to switch theory',
    'Change Goal': 'Change Goal',
    'Set Your Goal': 'Set Your Goal',
    'Goal type': 'Goal type',
    'Race Goal': 'Race Goal',
    'Train toward a specific race date': 'Train toward a specific race date',
    Continuous: 'Continuous',
    'Build fitness over time': 'Build fitness over time',
    Distance: 'Distance',
    'Race Date': 'Race Date',
    'Pick a date': 'Pick a date',
    'Target Time': 'Target Time',
    optional: 'optional',
    'Save Goal': 'Save Goal',
    'Saving…': 'Saving…',
    'Race date is required': 'Race date is required',
    'Invalid time format. Use H:MM:SS or H:MM': 'Invalid time format. Use H:MM:SS or H:MM',
    'Failed to save goal': 'Failed to save goal',
    'Leave blank to track predicted time only': 'Leave blank to track predicted time only',
    'What time are you working toward? Leave blank to track trend only':
      'What time are you working toward? Leave blank to track trend only',
    'Reality Check': 'Reality Check',
    'Fitness Trend': 'Fitness Trend',
    'Current Fitness': 'Current Fitness',
    Trend: 'Trend',
    Milestones: 'Milestones',
    Assessment: 'Assessment',
    'Estimated time to target': 'Estimated time to target',
    Comfortable: 'Comfortable',
    Stretch: 'Stretch',
    'Realistic targets': 'Realistic targets',
    'How this is calculated': 'How this is calculated',
    current: 'current',
    'Training base': 'Training base',
    Power: 'Power',
    'Heart rate': 'Heart rate',
    Pace: 'Pace',
    'What metric Praxys uses to measure intensity. Power needs Stryd; Pace works with anything that gives you GPS.':
      'What metric Praxys uses to measure intensity. Power needs Stryd; Pace works with anything that gives you GPS.',
    'Unbind your WeChat profile from this Praxys account so you can sign in as a different user.':
      'Unbind your WeChat profile from this Praxys account so you can sign in as a different user.',
    "Couldn't unlink your account on the server. Try again in a moment, or sign out instead and contact support if it keeps failing.":
      "Couldn't unlink your account on the server. Try again in a moment, or sign out instead and contact support if it keeps failing.",
  },
  zh: {
    // Brand tagline — canonical wording per docs/brand/index.html.
    'Train like a pro. Whatever your level.': '像专业选手一样训练，无论水平高低。',
    'Sign in with WeChat': '使用微信登录',
    'Signing you in…': '正在登录…',
    'Sign-in failed': '登录失败',
    'Sign-in code unavailable. Please try again.': '微信登录码暂不可用，请稍后重试。',
    'WeChat sign-in is not configured on this server.': '此服务器尚未配置微信登录。',
    'Your session expired. Please sign in again.': '会话已过期，请重新登录。',
    'Sign in to Praxys': '登录 Praxys',
    'Link to Praxys': '关联 Praxys 账号',
    email: '邮箱',
    password: '密码',
    'Email and password are required': '请填写邮箱和密码',
    'New here? Sign up at': '没有账号？立即注册',
    'tap to copy URL': '点击复制链接',
    'URL copied': '链接已复制',
    Retry: '重试',
    OK: '好的',
    Switch: '切换',
    Cancel: '取消',
    'Switch Praxys account': '切换 Praxys 账号',
    'Unlinking…': '正在解绑…',
    // "Sync" the noun (sync source / button label) — separate from the
    // verb "Sync now". Mini program currently uses both interchangeably.
    Sync: '同步',
    'Sync now': '立即同步',
    'Syncing…': '同步中…',
    'Sync started in the background.': '已开始后台同步。',
    'Sync request failed. Try again from the web app if it persists.':
      '同步请求失败。如持续失败，请在网页端再试。',
    'Use this': '使用此理论',
    'Failed to switch theory': '切换理论失败',
    'Change Goal': '修改目标',
    'Set Your Goal': '设定目标',
    'Goal type': '目标类型',
    'Race Goal': '比赛目标',
    'Train toward a specific race date': '为特定比赛日期训练',
    Continuous: '持续提升',
    'Build fitness over time': '长期提升体能',
    Distance: '距离',
    'Race Date': '比赛日期',
    'Pick a date': '选择日期',
    'Target Time': '目标完赛时间',
    optional: '选填',
    'Save Goal': '保存目标',
    'Saving…': '保存中…',
    'Race date is required': '请填写比赛日期',
    'Invalid time format. Use H:MM:SS or H:MM': '时间格式无效，请使用 H:MM:SS 或 H:MM',
    'Failed to save goal': '保存目标失败',
    'Leave blank to track predicted time only': '留空仅显示预测完赛时间',
    'What time are you working toward? Leave blank to track trend only':
      '您的目标时间是？留空仅追踪趋势',
    'Reality Check': '现实检验',
    'Fitness Trend': '体能趋势',
    'Current Fitness': '当前体能',
    Trend: '趋势',
    Milestones: '里程碑',
    Assessment: '评估',
    'Estimated time to target': '达成目标预计时间',
    Comfortable: '稳健',
    Stretch: '冲击',
    'Realistic targets': '可行的目标',
    'How this is calculated': '计算方式说明',
    current: '当前',
    'Training base': '训练基准',
    Power: '功率',
    'Heart rate': '心率',
    Pace: '配速',
    'What metric Praxys uses to measure intensity. Power needs Stryd; Pace works with anything that gives you GPS.':
      'Praxys 用于衡量训练强度的指标。功率需要 Stryd；配速适用于任何具备 GPS 的设备。',
    'Unbind your WeChat profile from this Praxys account so you can sign in as a different user.':
      '解除当前 Praxys 账号与微信的关联，以便您切换到其他账号。',
    "Couldn't unlink your account on the server. Try again in a moment, or sign out instead and contact support if it keeps failing.":
      '服务器解绑失败。请稍后重试；如持续失败，请改为退出登录并联系客服。',
  },
};
