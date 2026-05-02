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
 *
 * The per-locale entries are split into per-section objects merged via
 * spread. Smaller object literals make duplicate-key bugs both easier to
 * spot when grepping AND impossible to land — adjacent sections live in
 * different objects, so any genuine duplicate is a clean spread-override
 * the section author can resolve, rather than a TS1117 surprise.
 */
import type { Locale } from './i18n-catalog';

// ---------------------------------------------------------------------------
// English passthroughs — keys map to themselves. Listing them keeps the
// typing symmetric and makes it obvious when a key was intentionally added
// here rather than pulled from web's lingui catalog.
// ---------------------------------------------------------------------------

const EN_AUTH = {
  'Train like a pro. Whatever your level.': 'Train like a pro. Whatever your level.',
  'Sign in with WeChat': 'Sign in with WeChat',
  'Signing you in…': 'Signing you in…',
  'Sign-in failed': 'Sign-in failed',
  'Sign-in code unavailable. Please try again.': 'Sign-in code unavailable. Please try again.',
  'WeChat sign-in is not configured on this server.': 'WeChat sign-in is not configured on this server.',
  'Your session expired. Please sign in again.': 'Your session expired. Please sign in again.',
  'Sign in to Praxys': 'Sign in to Praxys',
  'Link to Praxys': 'Link to Praxys',
  email: 'email',
  password: 'password',
  'Email and password are required': 'Email and password are required',
  'New here? Sign up at': 'New here? Sign up at',
  'tap to copy URL': 'tap to copy URL',
  'URL copied': 'URL copied',
  'Long press to save & share': 'Long press to save & share',
  Retry: 'Retry',
  OK: 'OK',
  Switch: 'Switch',
  Cancel: 'Cancel',
  'Switch Praxys account': 'Switch Praxys account',
  'Unlinking…': 'Unlinking…',
  // "Sync" the noun (sync source / button label) — separate from the
  // verb "Sync now". Mini program currently uses both interchangeably.
  Sync: 'Sync',
  'Sync now': 'Sync now',
  'Syncing…': 'Syncing…',
  'Sync started in the background.': 'Sync started in the background.',
  'Sync request failed. Try again from the web app if it persists.':
    'Sync request failed. Try again from the web app if it persists.',
  "Couldn't unlink your account on the server. Try again in a moment, or sign out instead and contact support if it keeps failing.":
    "Couldn't unlink your account on the server. Try again in a moment, or sign out instead and contact support if it keeps failing.",
};

const EN_GOAL = {
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
  '0:00:00 = no target time': '0:00:00 = no target time',
  'Leave blank to track predicted time only': 'Leave blank to track predicted time only',
  'What time are you working toward? Leave blank to track trend only':
    'What time are you working toward? Leave blank to track trend only',
  Comfortable: 'Comfortable',
  Stretch: 'Stretch',
  'Realistic targets': 'Realistic targets',
  'On target': 'On target',
  'Off target': 'Off target',
  'No plan': 'No plan',
  'How this is calculated': 'How this is calculated',
  Predicted: 'Predicted',
  Target: 'Target',
  '+ Set target': '+ Set target',
  'CP trend': 'CP trend',
  Needed: 'Needed',
  Gap: 'Gap',
  'Source — tap to copy URL': 'Source — tap to copy URL',
  'Discussion — tap to copy URL': 'Discussion — tap to copy URL',
  'Ultra distance caveat': 'Ultra distance caveat',
  // Goal status badge values (API uses lowercase snake_case)
  on_track: 'On track',
  close: 'Close',
  behind: 'Behind',
  unlikely: 'Unlikely',
  unknown: '—',
  // Discard-edits modal
  'Discard changes?': 'Discard changes?',
  'Your goal edits will be lost.': 'Your goal edits will be lost.',
  Discard: 'Discard',
  'Keep editing': 'Keep editing',
  // Goal page science notes (default fallback when backend gives none)
  'Predicted using Stryd race power model (5K at 103.8% CP, marathon at 89.9% CP).':
    'Predicted using Stryd race power model (5K at 103.8% CP, marathon at 89.9% CP).',
  "Predicted using Riegel's formula (T₂ = T₁ × (D₂/D₁)^1.06), treating threshold pace as ~10K effort.":
    "Predicted using Riegel's formula (T₂ = T₁ × (D₂/D₁)^1.06), treating threshold pace as ~10K effort.",
  "Ultra distance power fractions (50K+) are estimates with limited research backing. Riegel's exponent is validated only up to marathon distance. Predictions beyond marathon carry significantly higher uncertainty due to factors like fueling, terrain, heat, and pacing strategy that dominate ultra performance but are not captured by power/pace models.":
    "Ultra distance power fractions (50K+) are estimates with limited research backing. Riegel's exponent is validated only up to marathon distance. Predictions beyond marathon carry significantly higher uncertainty due to factors like fueling, terrain, heat, and pacing strategy that dominate ultra performance but are not captured by power/pace models.",
  // Unified goal headline — one-sentence verdict rendered as plain text.
  // Web uses JSX <Trans> with <strong> spans; miniapp builds a plain string.
  '{0} days to race day. Today\'s prediction is {1} against a target of {2}.':
    '{0} days to race day. Today\'s prediction is {1} against a target of {2}.',
  '{0} days to race day. Today\'s prediction is {1}.':
    '{0} days to race day. Today\'s prediction is {1}.',
  'Building toward {0} {1}. Current {2} {3}{4}, need {5}{4}.':
    'Building toward {0} {1}. Current {2} {3}{4}, need {5}{4}.',
  'Building toward {0}. Current {1} {2}{3}, need {4}{3}.':
    'Building toward {0}. Current {1} {2}{3}, need {4}{3}.',
  'Today\'s {0} prediction is {1}. {2} is {3} at {4}.':
    'Today\'s {0} prediction is {1}. {2} is {3} at {4}.',
  'Today\'s {0} prediction is {1}. {2} is {3}.':
    'Today\'s {0} prediction is {1}. {2} is {3}.',
  '{0} is {1}. Add more activities for a race-time prediction.':
    '{0} is {1}. Add more activities for a race-time prediction.',
  // Strip cell labels — also in web zh catalog but mirrored here for EN completeness
  'Days left': 'Days left',
  'To target': 'To target',
  Direction: 'Direction',
  // Used as prefix in "current CP / current LTHR" strip labels
  current: 'current',
};

const EN_TODAY = {
  'Training base': 'Training base',
  Power: 'Power',
  'Heart rate': 'Heart rate',
  Pace: 'Pace',
  // Section heading for the warnings list. Lived in web's Today.tsx until
  // PR #238 redesigned the page and dropped the warnings block; miniapp's
  // pages/today still renders warnings, so the key lives here now.
  Warnings: 'Warnings',
  // Recovery status — must mirror RecoveryStatus in types/api.ts exactly.
  normal: 'Normal',
  fresh: 'Fresh',
  fatigued: 'Fatigued',
  insufficient_data: 'Insufficient data',
  // Volume trend values (volume.trend field in DiagnosisData)
  increasing: 'Increasing',
  decreasing: 'Decreasing',
  stable: 'Stable',
  'What metric Praxys uses to measure intensity. Power needs Stryd; Pace works with anything that gives you GPS.':
    'What metric Praxys uses to measure intensity. Power needs Stryd; Pace works with anything that gives you GPS.',
  'Unbind your WeChat profile from this Praxys account so you can sign in as a different user.':
    'Unbind your WeChat profile from this Praxys account so you can sign in as a different user.',
  Splits: 'Splits',
  more: 'more',
  References: 'References',
  'Zone labels': 'Zone labels',
  'Currently using': 'Currently using',
  'latest estimate': 'latest estimate',
  'data points': 'data points',
  km: 'km',
  time: 'time',
  'avg W': 'avg W',
  'avg HR': 'avg HR',
  Peaked: 'Peaked',
  Fresh: 'Fresh',
  Neutral: 'Neutral',
  Fatigued: 'Fatigued',
  'Over-fatigued': 'Over-fatigued',
  'Zone distribution': 'Zone distribution',
  Rising: 'Rising',
  Falling: 'Falling',
  Flat: 'Flat',
  // Today / Training shared labels
  'Avg power': 'Avg power',
  'No data available yet.': 'No data available yet.',
  'No TSB data yet': 'No TSB data yet',
  HRV: 'HRV',
  'Upcoming workouts': 'Upcoming workouts',
  'Last activity': 'Last activity',
  Close: 'Close',
  // Today supporting-cell labels — technical handles, identical
  // across en/zh because they are the canonical short forms (web's
  // Today.tsx renders these as JSX literals for the same reason).
  'HRV (ln RMSSD)': 'HRV (ln RMSSD)',
  TSB: 'TSB',
  // Signal subtitles (Today page)
  'Follow Plan': 'Follow Plan',
  'Go Easy': 'Go Easy',
  'Adjust Workout': 'Adjust Workout',
  'Reduce Intensity': 'Reduce Intensity',
  'Recovery Day': 'Recovery Day',
  // Stale-data advisory. Mini program uses positional `{0}` placeholders
  // (tFmt) so the key differs from the web `{name}` form in
  // messages.po — this is the mini-only English passthrough used by
  // pages/today/index.ts:buildStalenessText.
  "Recovery data hasn't synced yet. Showing the latest reading from {0}.":
    "Recovery data hasn't synced yet. Showing the latest reading from {0}.",
};

const EN_TRAINING = {
  'No training data yet. Sync Garmin / Stryd from the web app (Settings → Sync) to populate this view.':
    'No training data yet. Sync Garmin / Stryd from the web app (Settings → Sync) to populate this view.',
  Volume: 'Volume',
  'Fitness & Fatigue': 'Fitness & Fatigue',
  Consistency: 'Consistency',
  'Show correlation': 'Show correlation',
  'Hide correlation': 'Hide correlation',
  // Training page interpolated copy
  '{0} km/week': '{0} km/week',
  'trend: {0}': 'trend: {0}',
  '{0} sessions · gaps ≥7d: {1} · longest: {2}d':
    '{0} sessions · gaps ≥7d: {1} · longest: {2}d',
  '{0} · {1}': '{0} · {1}',
  // Detail messages
  'Need at least 3 activities with power data to plot a meaningful trend.':
    'Need at least 3 activities with power data to plot a meaningful trend.',
  'Sync activities together with sleep data (Garmin, Oura, or similar) so we can pair them by date.':
    'Sync activities together with sleep data (Garmin, Oura, or similar) so we can pair them by date.',
  'Sync at least 2 weeks of data to compare planned vs actual training load.':
    'Sync at least 2 weeks of data to compare planned vs actual training load.',
  'Planned bars are estimated — your plan has no RSS targets for this base.':
    'Planned bars are estimated — your plan has no RSS targets for this base.',
};

const EN_HISTORY_SCIENCE = {
  // History page footers
  'Loading more…': 'Loading more…',
  'Tap to view {0} splits': 'Tap to view {0} splits',
  'End of activities': 'End of activities',
  '{0} total · showing {1}': '{0} total · showing {1}',
  // Science page intro / recommendation
  "Praxys's numbers come from published research. These are the theories currently powering your dashboard, plus the alternatives you could switch to on the web.":
    "Praxys's numbers come from published research. These are the theories currently powering your dashboard, plus the alternatives you could switch to on the web.",
  'Based on your training, we suggest': 'Based on your training, we suggest',
  'No active theory configured.': 'No active theory configured.',
  '{0} label sets available — switch on the web.':
    '{0} label sets available — switch on the web.',
  // Transitional fallbacks: web's Science page redesign (PR #259) replaced
  // these strings with new copy. The miniapp Science page will be
  // redesigned for parity in a follow-up PR; until then these keep
  // pages/science/index.ts rendering rather than falling through to the
  // raw English. Remove when miniapp parity ships.
  Simple: 'Simple',
  Advanced: 'Advanced',
  'How does training stress become fitness?': 'How does training stress become fitness?',
  'How do we assess readiness to train?': 'How do we assess readiness to train?',
  'How do we estimate race potential?': 'How do we estimate race potential?',
  'How is intensity classified?': 'How is intensity classified?',
};

const EN_SETTINGS = {
  Name: 'Name',
  // Unit system — must mirror UnitSystem in types/api.ts exactly.
  metric: 'Metric',
  imperial: 'Imperial',
  Connections: 'Connections',
  'Manage connections from the web app.': 'Manage connections from the web app.',
  "No platforms connected. Link Garmin / Stryd / Oura from the web app — their OAuth flows aren't supported in mini programs.":
    "No platforms connected. Link Garmin / Stryd / Oura from the web app — their OAuth flows aren't supported in mini programs.",
  'Auto-detected from synced fitness data; override on the web.':
    'Auto-detected from synced fitness data; override on the web.',
  'No thresholds yet. Sync Garmin / Stryd data to auto-detect CP, LTHR, and pace — or enter values manually on the web.':
    'No thresholds yet. Sync Garmin / Stryd data to auto-detect CP, LTHR, and pace — or enter values manually on the web.',
  'Browse the load / recovery / prediction / zone theories':
    'Browse the load / recovery / prediction / zone theories',
  'Open Praxys on web': 'Open Praxys on web',
  "This unlinks your WeChat profile from the current Praxys account. You'll be signed out and can sign in to a different account on next launch.":
    "This unlinks your WeChat profile from the current Praxys account. You'll be signed out and can sign in to a different account on next launch.",
  // Threshold labels
  CP: 'CP',
  LTHR: 'LTHR',
  'Threshold pace': 'Threshold pace',
  'Max HR': 'Max HR',
  'Resting HR': 'Resting HR',
  'from {0}': 'from {0}',
};

const EN_NAV_CHARTS = {
  // Page titles (for nav-bar / custom-tab-bar)
  Today: 'Today',
  // Sleep perf metric label — API can return "Avg Pace" when base is pace
  'Avg Pace': 'Avg Pace',
  Training: 'Training',
  Activities: 'Activities',
  Goal: 'Goal',
  Settings: 'Settings',
  'Training Science': 'Training Science',
  'Training science': 'Training science',
  // Chart axis / series labels
  'Sleep Score': 'Sleep Score',
  'Sleep Score vs Avg Power': 'Sleep Score vs Avg Power',
  'Sleep Score vs {0}': 'Sleep Score vs {0}',
  'Avg Power': 'Avg Power',
  'Fitness (CTL)': 'Fitness (CTL)',
  'Fatigue (ATL)': 'Fatigue (ATL)',
  // Chart fallback messages
  'Not enough data': 'Not enough data',
  'No data': 'No data',
  // Scatter chart tooltip
  'Sleep {0} · {1}': 'Sleep {0} · {1}',
};

// ---------------------------------------------------------------------------
// Chinese translations — same key shape as the English passthroughs above,
// values translated.
// ---------------------------------------------------------------------------

const ZH_AUTH = {
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
  'Long press to save & share': '长按保存并分享',
  Retry: '重试',
  OK: '好的',
  Switch: '切换',
  Cancel: '取消',
  'Switch Praxys account': '切换 Praxys 账号',
  'Unlinking…': '正在解绑…',
  Sync: '同步',
  'Sync now': '立即同步',
  'Syncing…': '同步中…',
  'Sync started in the background.': '已开始后台同步。',
  'Sync request failed. Try again from the web app if it persists.':
    '同步请求失败。如持续失败，请在网页端再试。',
  "Couldn't unlink your account on the server. Try again in a moment, or sign out instead and contact support if it keeps failing.":
    '服务器解绑失败。请稍后重试；如持续失败，请改为退出登录并联系客服。',
};

const ZH_GOAL = {
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
  '0:00:00 = no target time': '0:00:00 = 不设目标时间',
  'Leave blank to track predicted time only': '留空仅显示预测完赛时间',
  'What time are you working toward? Leave blank to track trend only':
    '您的目标时间是？留空仅追踪趋势',
  Comfortable: '稳健',
  Stretch: '冲击',
  'Realistic targets': '可行的目标',
  'On target': '达标',
  'Off target': '偏离目标',
  'No plan': '无计划',
  'How this is calculated': '计算方式说明',
  Predicted: '预测',
  Target: '目标',
  '+ Set target': '+ 设置目标',
  'CP trend': 'CP 趋势',
  Needed: '所需',
  Gap: '差距',
  'Source — tap to copy URL': '来源 — 点击复制链接',
  'Discussion — tap to copy URL': '讨论 — 点击复制链接',
  'Ultra distance caveat': '超长距离说明',
  // Goal status badge values (lowercase API keys)
  on_track: '达标',
  close: '接近',
  behind: '落后',
  unlikely: '难以实现',
  unknown: '—',
  // Discard-edits modal
  'Discard changes?': '放弃修改？',
  'Your goal edits will be lost.': '您当前的目标修改将丢失。',
  Discard: '放弃',
  'Keep editing': '继续编辑',
  // Science notes
  'Predicted using Stryd race power model (5K at 103.8% CP, marathon at 89.9% CP).':
    '依据 Stryd 比赛功率模型预测 (5K 为阈值功率的 103.8%，全程马拉松为 89.9%)。',
  "Predicted using Riegel's formula (T₂ = T₁ × (D₂/D₁)^1.06), treating threshold pace as ~10K effort.":
    '依据 Riegel 公式预测 (T₂ = T₁ × (D₂/D₁)^1.06)，将阈值配速视为约 10K 强度。',
  "Ultra distance power fractions (50K+) are estimates with limited research backing. Riegel's exponent is validated only up to marathon distance. Predictions beyond marathon carry significantly higher uncertainty due to factors like fueling, terrain, heat, and pacing strategy that dominate ultra performance but are not captured by power/pace models.":
    '超长距离 (50K 及以上) 的功率分配比例为估算值，研究数据有限。Riegel 公式的指数仅在全程马拉松以内得到验证。马拉松以上距离的预测不确定性显著上升，因为补给、地形、温度和配速策略等主导超长距离表现的因素无法被功率/配速模型完全捕捉。',
  // Unified goal headline zh translations
  '{0} days to race day. Today\'s prediction is {1} against a target of {2}.':
    '距比赛日还有 {0} 天。今日预测 {1}，目标 {2}。',
  '{0} days to race day. Today\'s prediction is {1}.':
    '距比赛日还有 {0} 天。今日预测 {1}。',
  'Building toward {0} {1}. Current {2} {3}{4}, need {5}{4}.':
    '冲刺 {1} {0}。当前{2} {3}{4}，目标 {5}{4}。',
  'Building toward {0}. Current {1} {2}{3}, need {4}{3}.':
    '冲刺 {0}。当前{1} {2}{3}，目标 {4}{3}。',
  'Today\'s {0} prediction is {1}. {2} is {3} at {4}.':
    '今日{0}预测 {1}。{2}趋势{3}，速率{4}。',
  'Today\'s {0} prediction is {1}. {2} is {3}.':
    '今日{0}预测 {1}。{2}趋势{3}。',
  '{0} is {1}. Add more activities for a race-time prediction.':
    '{0}趋势{1}。积累更多训练数据以获取比赛预测成绩。',
  'Days left': '剩余天数',
  'To target': '距目标',
  Direction: '趋势方向',
  current: '当前',
};

const ZH_TODAY = {
  'Training base': '训练基准',
  Power: '功率',
  'Heart rate': '心率',
  Pace: '配速',
  Warnings: '警告',
  // Recovery status — must mirror RecoveryStatus in types/api.ts exactly.
  normal: '正常',
  fresh: '恢复良好',
  fatigued: '疲劳',
  insufficient_data: '数据不足',
  // Volume trend values (volume.trend field in DiagnosisData)
  increasing: '上升中',
  decreasing: '下降中',
  stable: '平稳',
  'What metric Praxys uses to measure intensity. Power needs Stryd; Pace works with anything that gives you GPS.':
    'Praxys 用于衡量训练强度的指标。功率需要 Stryd；配速适用于任何具备 GPS 的设备。',
  'Unbind your WeChat profile from this Praxys account so you can sign in as a different user.':
    '解除当前 Praxys 账号与微信的关联，以便您切换到其他账号。',
  Splits: '分段',
  more: '更多',
  References: '参考文献',
  'Zone labels': '区间标签',
  'Currently using': '当前使用',
  'latest estimate': '最新估算',
  'data points': '个数据点',
  km: '公里',
  time: '时间',
  'avg W': '均功',
  'avg HR': '均心率',
  Peaked: '超量',
  Fresh: '恢复良好',
  Neutral: '中性',
  Fatigued: '疲劳',
  'Over-fatigued': '过度疲劳',
  'Zone distribution': '区间分布',
  Rising: '上升',
  Falling: '下降',
  Flat: '平稳',
  'Avg power': '平均功率',
  'No data available yet.': '暂无数据。',
  'No TSB data yet': '暂无状态 (TSB) 数据',
  HRV: '心率变异 (HRV)',
  'Upcoming workouts': '计划训练',
  'Last activity': '最近活动',
  Close: '关闭',
  // Today supporting-cell technical handles — kept untranslated so
  // the cell label matches what the user reads on the web Today
  // page. The cell value below the label disambiguates anyway
  // (today_ln value, signed TSB, etc.).
  'HRV (ln RMSSD)': 'HRV (ln RMSSD)',
  TSB: 'TSB',
  // Signal subtitles
  'Follow Plan': '执行计划',
  'Go Easy': '轻松进行',
  'Adjust Workout': '调整训练',
  'Reduce Intensity': '降低强度',
  'Recovery Day': '恢复日',
  // Stale-data advisory. `{0}` is the localized reading-date chip
  // ("Apr 24" / "4月24日") supplied by tFmt.
  "Recovery data hasn't synced yet. Showing the latest reading from {0}.":
    '今日恢复数据尚未同步，显示的是 {0} 的最近读数。',
};

const ZH_TRAINING = {
  'No training data yet. Sync Garmin / Stryd from the web app (Settings → Sync) to populate this view.':
    '暂无训练数据。请在网页端 (设置 → 同步) 同步 Garmin / Stryd 数据以填充此视图。',
  Volume: '训练量',
  'Fitness & Fatigue': '体能与疲劳',
  Consistency: '训练频率',
  'Show correlation': '显示相关性',
  'Hide correlation': '隐藏相关性',
  '{0} km/week': '{0} 公里/周',
  'trend: {0}': '趋势：{0}',
  '{0} sessions · gaps ≥7d: {1} · longest: {2}d':
    '{0} 次训练 · ≥7 天间隔：{1} 次 · 最长间隔：{2} 天',
  '{0} · {1}': '{0} · {1}',
  'Need at least 3 activities with power data to plot a meaningful trend.':
    '至少需要 3 次带功率数据的活动才能绘制有意义的趋势。',
  'Sync activities together with sleep data (Garmin, Oura, or similar) so we can pair them by date.':
    '请同时同步活动与睡眠数据 (Garmin、Oura 或类似设备)，以便按日期匹配。',
  'Sync at least 2 weeks of data to compare planned vs actual training load.':
    '请同步至少 2 周的数据，以便对比计划与实际训练负荷。',
  'Planned bars are estimated — your plan has no RSS targets for this base.':
    '计划数值为估算结果——您的训练计划在当前基准下未设置 RSS 目标。',
};

const ZH_HISTORY_SCIENCE = {
  'Loading more…': '正在加载更多…',
  'Tap to view {0} splits': '点击查看 {0} 个分段',
  'End of activities': '已加载全部活动',
  '{0} total · showing {1}': '共 {0} 条 · 当前显示 {1}',
  "Praxys's numbers come from published research. These are the theories currently powering your dashboard, plus the alternatives you could switch to on the web.":
    'Praxys 的数据均来自已发表的研究文献。以下是当前驱动您仪表板的理论，以及您可在网页端切换的替代方案。',
  'Based on your training, we suggest': '根据您的训练数据，我们推荐',
  'No active theory configured.': '尚未配置启用的理论。',
  '{0} label sets available — switch on the web.':
    '可选的区间标签集共 {0} 套——请在网页端切换。',
  // Transitional fallbacks — see EN_HISTORY_SCIENCE comment above.
  Simple: '简要',
  Advanced: '详细',
  'How does training stress become fitness?': '训练应激如何转化为体能？',
  'How do we assess readiness to train?': '如何评估训练准备度？',
  'How do we estimate race potential?': '如何估算比赛潜力？',
  'How is intensity classified?': '如何分类训练强度？',
};

const ZH_SETTINGS = {
  Name: '姓名',
  // Unit system — must mirror UnitSystem in types/api.ts exactly.
  metric: '公制',
  imperial: '英制',
  Connections: '已连接平台',
  'Manage connections from the web app.': '请在网页端管理已连接的平台。',
  "No platforms connected. Link Garmin / Stryd / Oura from the web app — their OAuth flows aren't supported in mini programs.":
    '尚未连接任何平台。请在网页端连接 Garmin / Stryd / Oura——这些平台的 OAuth 授权流程在小程序中不受支持。',
  'Auto-detected from synced fitness data; override on the web.':
    '依据已同步的体能数据自动识别；如需覆盖，请在网页端修改。',
  'No thresholds yet. Sync Garmin / Stryd data to auto-detect CP, LTHR, and pace — or enter values manually on the web.':
    '暂无阈值数据。请同步 Garmin / Stryd 数据以自动识别阈值功率、乳酸阈值心率和阈值配速；您也可以在网页端手动填入。',
  'Browse the load / recovery / prediction / zone theories': '浏览负荷 / 恢复 / 预测 / 区间四类理论',
  'Open Praxys on web': '在网页端打开 Praxys',
  "This unlinks your WeChat profile from the current Praxys account. You'll be signed out and can sign in to a different account on next launch.":
    '此操作将解除您的微信账号与当前 Praxys 账号的关联。您将被退出登录，下次启动时可使用其他账号登录。',
  // Threshold labels — preferred zh terminology per project conventions.
  CP: '阈值功率 (CP)',
  LTHR: '乳酸阈值心率 (LTHR)',
  'Threshold pace': '阈值配速',
  'Max HR': '最大心率',
  'Resting HR': '静息心率',
  'from {0}': '来源：{0}',
};

const ZH_NAV_CHARTS = {
  Today: '今日',
  'Avg Pace': '平均配速',
  Training: '训练',
  Activities: '活动记录',
  Goal: '目标',
  Settings: '设置',
  'Training Science': '训练科学',
  'Training science': '训练科学',
  'Sleep Score': '睡眠评分',
  'Sleep Score vs Avg Power': '睡眠评分与平均功率',
  'Sleep Score vs {0}': '睡眠评分与{0}',
  'Avg Power': '平均功率',
  'Fitness (CTL)': '体能 (CTL)',
  'Fatigue (ATL)': '疲劳 (ATL)',
  'Not enough data': '数据不足',
  'No data': '暂无数据',
  'Sleep {0} · {1}': '睡眠 {0} · {1}',
};

export const I18N_EXTRA: Record<Locale, Record<string, string>> = {
  en: {
    ...EN_AUTH,
    ...EN_GOAL,
    ...EN_TODAY,
    ...EN_TRAINING,
    ...EN_HISTORY_SCIENCE,
    ...EN_SETTINGS,
    ...EN_NAV_CHARTS,
  },
  zh: {
    ...ZH_AUTH,
    ...ZH_GOAL,
    ...ZH_TODAY,
    ...ZH_TRAINING,
    ...ZH_HISTORY_SCIENCE,
    ...ZH_SETTINGS,
    ...ZH_NAV_CHARTS,
  },
};
