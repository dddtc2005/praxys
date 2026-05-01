import { setTabBarSelected } from '../../utils/tabbar';
import type { IAppOption } from '../../app';
import { apiGet } from '../../utils/api-client';
import { generateShareCard } from '../../utils/share-image';
import type { ApiError } from '../../utils/api-client';
import type {
  AiInsight,
  AiInsightFinding,
  PlanData,
  RecoveryAnalysis,
  TodayResponse,
} from '../../types/api';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { t, tFmt, detectLocale } from '../../utils/i18n';
import { fetchInsight, localizedInsight } from '../../utils/insights';
import {
  buildShareMessage,
  buildTimelineMessage,
  detectShareLocale,
  getShareMessage,
} from '../../utils/share';

interface SignalMeta {
  label: string;
  subtitle: string;
  color: 'green' | 'amber' | 'red';
}

// Mirrors web/src/components/SignalHero.tsx — same labels, subtitles,
// and color buckets so the visual status reads identically across web
// and mini. Subtitles route through t() so they read in the active
// locale; the labels themselves stay in English (GO/EASY/REST/…) as
// short status glyphs that read identically across locales.
function signalMeta(): Record<string, SignalMeta> {
  return {
    follow_plan: { label: 'GO', subtitle: t('Follow Plan'), color: 'green' },
    easy: { label: 'EASY', subtitle: t('Go Easy'), color: 'amber' },
    modify: { label: 'MODIFY', subtitle: t('Adjust Workout'), color: 'amber' },
    reduce_intensity: { label: 'CAUTION', subtitle: t('Reduce Intensity'), color: 'amber' },
    rest: { label: 'REST', subtitle: t('Recovery Day'), color: 'red' },
  };
}

type CoachMarker = '[+]' | '[!]' | '[·]';

interface CoachFindingRow {
  /** Stable unique key for `wx:key` — array position is sufficient since
   *  findings are consumed read-only. Plain `text` is unsafe because two
   *  findings can share copy (e.g. repeated neutral notes across days),
   *  which would collide and confuse Skyline's reconciler. */
  id: string;
  /** Glyph derived from `tone`; same convention as web's coach-receipt. */
  marker: CoachMarker;
  /** Tone class suffix used for `coach-row--{{tone}}` styling. */
  tone: AiInsightFinding['type'];
  text: string;
}

interface CoachRecRow {
  /** 1-based ordinal as a string for WXML rendering. Doubles as the
   *  `wx:key` since recommendations are presented in a stable order. */
  index: string;
  text: string;
}

interface CoachReceipt {
  /** Time-since-generated, e.g. "2h ago" / "5分钟前". Empty when no
   *  generated_at on the row (legacy inserts). */
  stamp: string;
  headline: string;
  hasFindings: boolean;
  findings: CoachFindingRow[];
  hasRecommendations: boolean;
  recommendations: CoachRecRow[];
  /** Active recovery + load theory names joined with ` · `. Empty when
   *  the API didn't surface science_notes (e.g. fresh user before
   *  first sync). */
  attribution: string;
}

/** Pre-translated coach-receipt copy. Captured in render state so WXML
 *  stays stringless and `check-i18n.cjs` doesn't flag the template. */
interface CoachTranslations {
  mark: string;
  findings: string;
  recommendations: string;
  aria: string;
}

/** A single supporting metric cell — flat 2-col grid mirrors web's
 *  PR #238 layout. Five cells: HRV / 7d Trend / RHR / Sleep / TSB. */
interface SupportingCell {
  /** Stable unique key for `wx:key`. */
  id: string;
  /** Mono uppercase eyebrow above the value. */
  label: string;
  /** Large mono value (or `—` when no data). */
  value: string;
  /** Mono muted caption below the value. */
  sub: string;
  /** Optional accent class on `.today-cell-value` — used to tint TSB
   *  green when freshness is positive. Empty string means no accent. */
  valueAccent: string;
}

/**
 * Format a relative-time stamp ("2h ago" / "5分钟前") for the coach
 * receipt header. Buckets into minute / hour / day via
 * `Intl.RelativeTimeFormat` — Skyline's Intl support is base-library
 * dependent, and an older runtime that lacks `RelativeTimeFormat`, or
 * a malformed ISO date, falls back to an empty string (the headline
 * and body still read; the `wx:if="{{coach.stamp}}"` gate hides the
 * empty chip cleanly).
 */
function timeAgo(isoDate: string, locale: 'en' | 'zh'): string {
  try {
    const diff = Date.now() - new Date(isoDate).getTime();
    const rtf = new Intl.RelativeTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { style: 'short' });
    const mins = Math.floor(diff / 60_000);
    if (mins < 60) return rtf.format(-mins, 'minute');
    const hours = Math.floor(mins / 60);
    if (hours < 24) return rtf.format(-hours, 'hour');
    const days = Math.floor(hours / 24);
    return rtf.format(-days, 'day');
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[today] timeAgo failed; dropping stamp:', isoDate, e);
    return '';
  }
}

function buildCoachReceipt(
  insight: AiInsight,
  locale: 'en' | 'zh',
  recoveryName: string | undefined,
  loadName: string | undefined,
): CoachReceipt {
  const view = localizedInsight(insight, locale);
  const findings: CoachFindingRow[] = view.findings.map((f, i) => ({
    id: `${i}`,
    marker: f.type === 'positive' ? '[+]' : f.type === 'warning' ? '[!]' : '[·]',
    tone: f.type,
    text: f.text,
  }));
  const recommendations: CoachRecRow[] = view.recommendations.map((r, i) => ({
    index: `${i + 1}`,
    text: r,
  }));
  const attribution = [recoveryName, loadName].filter((s): s is string => !!s).join(' · ');
  return {
    stamp: insight.generated_at ? timeAgo(insight.generated_at, locale) : '',
    headline: view.headline,
    hasFindings: findings.length > 0,
    findings,
    hasRecommendations: recommendations.length > 0,
    recommendations,
    attribution,
  };
}

const TREND_ARROW: Record<'stable' | 'improving' | 'declining', string> = {
  stable: '→',
  improving: '↑',
  declining: '↓',
};

// Banister PMC interpretation of training stress balance (TSB):
//   ≥ +10  strongly positive — peaked freshness, primed to perform
//   0..10  positive — freshness, training adapted
//   -10..0 mild fatigue — adaptation in progress
//   < -10  fatigued — accumulated fatigue, recovery prioritized
// Source: Banister, E.W. (1991). Modeling elite athletic performance.
const TSB_STRONGLY_POSITIVE = 10;
const TSB_MILD_FATIGUE = -10;

function tsbDescriptor(tsb: number): string {
  if (tsb >= TSB_STRONGLY_POSITIVE) return t('strongly positive');
  if (tsb > 0) return t('positive');
  if (tsb > TSB_MILD_FATIGUE) return t('mild fatigue');
  return t('fatigued');
}

/** Build the 5-cell supporting metrics row that replaces the prior
 *  Form/TSB sparkline + Recovery card. Order mirrors web's PR #238:
 *  HRV, 7d Trend, RHR, Sleep, TSB. */
function buildSupportingCells(
  ra: RecoveryAnalysis | null,
  tsb: number,
): SupportingCell[] {
  const noData = t('no data');
  const hrv = ra?.hrv ?? null;

  // Cell 1 — HRV (today's ln RMSSD).
  const hrvValue = hrv ? hrv.today_ln.toFixed(2) : '—';
  const hrvSub = hrv
    ? (hrv.today_ms != null ? `${hrv.today_ms} ms · ` : '') +
      tFmt('vs {0} baseline', hrv.baseline_mean_ln.toFixed(2))
    : noData;

  // Cell 2 — 7d Trend (arrow + label + rolling CV%).
  const trendValue = hrv ? TREND_ARROW[hrv.trend] : '—';
  const trendSub = hrv
    ? `${t(hrv.trend)} · CV ${hrv.rolling_cv.toFixed(1)}%`
    : noData;

  // Cell 3 — Resting HR. Round the 7-day mean float; only show the
  // trend chip when the API actually emits one (the API returns null
  // for "no signal" — falling back to a literal "normal" would assert
  // information that isn't there).
  const rhrValue = ra?.resting_hr != null ? `${Math.round(ra.resting_hr)}` : '—';
  let rhrSub: string;
  if (ra?.resting_hr == null) {
    rhrSub = noData;
  } else if (ra.rhr_trend) {
    rhrSub = `bpm · ${t(ra.rhr_trend)}`;
  } else {
    rhrSub = 'bpm';
  }

  // Cell 4 — Sleep score (Oura/Garmin overnight score, 0–100).
  const sleepValue = ra?.sleep_score != null ? `${ra.sleep_score.toFixed(0)}` : '—';
  const sleepSub = ra?.sleep_score != null ? t('overnight score') : noData;

  // Cell 5 — TSB (signed, 1dp). Tint green when freshness is positive.
  const tsbValue = `${tsb >= 0 ? '+' : ''}${tsb.toFixed(1)}`;
  const tsbAccent = tsb > 0 ? 'today-cell-value-positive' : '';

  return [
    { id: 'hrv', label: t('HRV (ln RMSSD)'), value: hrvValue, sub: hrvSub, valueAccent: '' },
    { id: 'trend', label: t('7d Trend'), value: trendValue, sub: trendSub, valueAccent: '' },
    { id: 'rhr', label: t('RHR'), value: rhrValue, sub: rhrSub, valueAccent: '' },
    { id: 'sleep', label: t('Sleep'), value: sleepValue, sub: sleepSub, valueAccent: '' },
    { id: 'tsb', label: t('TSB'), value: tsbValue, sub: tsbDescriptor(tsb), valueAccent: tsbAccent },
  ];
}

/** Format the planned-workout one-liner. Returns the rest-day fallback
 *  when no workout is scheduled. Mirrors web/src/pages/Today.tsx. */
function formatPlan(plan: PlanData | null | undefined): string {
  if (!plan?.workout_type) return t('Rest day. No workout scheduled.');
  const parts: string[] = [plan.workout_type];
  if (plan.distance_km != null) parts.push(`${plan.distance_km.toFixed(1)} km`);
  if (plan.duration_min != null) parts.push(`${plan.duration_min} min`);
  if (plan.power_min != null && plan.power_max != null) {
    parts.push(`${plan.power_min}–${plan.power_max} W`);
  }
  return parts.join(' · ');
}

interface RenderState {
  themeClass: string;
  /** 'light' | 'dark' — narrow form retained because the share-card
   *  generator and theme-toggle path still consume it. */
  chartTheme: 'light' | 'dark';
  today: string;
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;

  signalLabel: string;
  signalSubtitle: string;
  signalColor: 'green' | 'amber' | 'red';
  /** Rule-based reason text. Invariant: empty string iff `hasCoach`
   *  is true — the Coach receipt below covers the same ground in a
   *  more specific voice, so we render only one. WXML's
   *  `wx:if="{{signalReason}}"` treats `''` as falsy and skips the
   *  block. Rule-based prose is the deterministic fallback when the
   *  brief is missing (LLM disabled, transient endpoint failure). */
  signalReason: string;
  hasCoach: boolean;
  coach: CoachReceipt | null;
  coachTr: CoachTranslations | null;

  /** Five supporting metrics in source order: HRV, 7d Trend, RHR,
   *  Sleep, TSB. Always present once `hasResponse` is true; cells
   *  show `—` for absent data with a `no data` sub. */
  cells: SupportingCell[];

  planEyebrow: string;
  planText: string;

  hasWarnings: boolean;
  warnings: string[];
}

function buildRenderState(
  response: TodayResponse | null,
  themeClass: string,
  today: string,
  insight: AiInsight | null,
): Partial<RenderState> {
  if (!response) {
    return {};
  }

  const meta = signalMeta()[response.signal.recommendation] ?? signalMeta().follow_plan;

  // Coach receipt: the LLM-generated daily brief, rendered between the
  // signal hero and the supporting cells. When present, suppresses the
  // rule-based signal.reason above so the user doesn't read the same
  // idea twice in two voices. A throw inside buildCoachReceipt (e.g.
  // a future schema change yields an unexpected finding shape) must
  // not blank the whole page — degrade to "no receipt" and let the
  // rule-based prose re-appear.
  const locale = detectLocale();
  const recoveryNoteName = response.science_notes?.recovery?.name;
  const loadNoteName = response.science_notes?.load?.name;
  let coach: CoachReceipt | null = null;
  if (insight) {
    try {
      coach = buildCoachReceipt(insight, locale, recoveryNoteName, loadNoteName);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[today] coach receipt build failed; suppressing receipt:', e);
    }
  }
  const hasCoach = coach != null;
  const coachTr: CoachTranslations | null = hasCoach
    ? {
        mark: t('Praxys Coach'),
        findings: t('Findings'),
        recommendations: t('Recommendations'),
        aria: t('Praxys Coach insight'),
      }
    : null;

  const cells = buildSupportingCells(
    response.recovery_analysis ?? null,
    response.signal.recovery.tsb,
  );

  const warnings = response.warnings ?? [];

  return {
    themeClass,
    today,
    loading: false,
    errorMessage: '',
    hasResponse: true,

    signalLabel: meta.label,
    signalSubtitle: meta.subtitle,
    signalColor: meta.color,
    signalReason: hasCoach ? '' : response.signal.reason,
    hasCoach,
    coach,
    coachTr,

    cells,

    planEyebrow: t('Planned · Today'),
    planText: formatPlan(response.signal.plan),

    hasWarnings: warnings.length > 0,
    warnings,
  };
}

function todayFormatted(): string {
  // Match the active locale for the date string — Chinese gets the
  // native date format (2026年4月27日 周一) instead of English.
  const locale = detectLocale();
  return new Date().toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

// Pre-translate UI strings once at page load. Locale changes trigger a
// reLaunch (Settings → Language → reLaunch settings), so this doesn't
// need to react to live locale changes.
function buildTranslations() {
  return {
    navTitle: t('Today'),
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    noDataYet: t('No data available yet.'),
    warnings: t('Warnings'),
    close: t('Close'),
  };
}

interface RefreshState {
  refreshing: boolean;
  /** Whether the share card image is currently shown. Toggled by the
   *  FAB — the card only appears on demand, not on every page load. */
  shareCardVisible: boolean;
  shareImagePath: string;
  /** Theme the cached share card was rendered at. Used to detect when a
   *  theme change means the cached image needs to be re-generated. */
  shareCardTheme: 'light' | 'dark' | '';
}

const initialData: RenderState & RefreshState = {
  themeClass: getApp<IAppOption>().globalData.themeClass,
  chartTheme: 'light',
  today: '',
  loading: true,
  errorMessage: '',
  hasResponse: false,
  refreshing: false,

  signalLabel: '',
  signalSubtitle: '',
  signalColor: 'green',
  signalReason: '',
  hasCoach: false,
  coach: null,
  coachTr: null,

  cells: [],

  planEyebrow: '',
  planText: '',

  hasWarnings: false,
  warnings: [],

  shareImagePath: '',
  shareCardVisible: false,
  shareCardTheme: '',
};

// Translation table — built per page-load (Locale changes reLaunch).
const initialTr = buildTranslations();

Page({
  data: { ...initialData, tr: initialTr },

  onLoad() {
    const tc = themeClassName();
    this.setData({
      themeClass: tc,
      chartTheme: tc === 'theme-light' ? 'light' : 'dark',
      today: todayFormatted(),
      tr: buildTranslations(),
    });
    // Allow sharing via the WeChat ⋯ menu. Without this call, Skyline
    // pages show "当前页面未设置分享" in the system share sheet.
    wx.showShareMenu({
      withShareTicket: false,
      menus: ['shareAppMessage', 'shareTimeline'],
      fail: () => { /* some older clients don't support menus param */ },
    });
    void this.refetch();
  },

  onShow() {
    // Guarded theme update: other tabs can't be reached by getCurrentPages()
    // from Settings, so if the user changed theme while on another tab,
    // this is the first chance to apply it. Equality check prevents
    // re-renders on normal tab switches where nothing changed.
    const tc = themeClassName();
    if (tc !== this.data.themeClass) {
      this.setData({ themeClass: tc, chartTheme: tc === 'theme-light' ? 'light' : 'dark' });
    }
    // Locale guard: rebuilds tr when language changed while this tab
    // was not active (same pattern as theme — globalData stores the
    // active locale so we detect drift without a storage read).
    const curLocale = getApp<IAppOption>().globalData.locale;
    const pgMut = this as unknown as Record<string, unknown>;
    if (curLocale !== pgMut._locale) {
      pgMut._locale = curLocale;
      this.setData({ tr: buildTranslations() });
      void this.refetch();
    }
    applyThemeChrome();
    setTabBarSelected(this, 0);
  },

  onShareAppMessage(options: WechatMiniprogram.Page.IShareAppMessageOption) {
    // Two share paths distinguished by `options.from`:
    //   - 'menu'   (top-right ⋯): generic Praxys share, brand og-card.
    //   - 'button' (signal-card FAB): personalized title with the
    //              user's current signal, but the same bundled brand
    //              image as the cover.
    //
    // We deliberately do NOT pass the canvas-rendered tempFilePath as
    // `imageUrl`. On unverified personal mini programs, WeChat shows a
    // "微信认证 (verification) required" advisory when shares use a
    // tempFilePath (`wxfile://...`) thumbnail. Using the project-bundled
    // /assets/og-card-wechat.jpg avoids the prompt entirely. Once the
    // mini program is enterprise-verified, we can swap back to the
    // dynamic image without changing the rest of the flow.
    const fromButton = options?.from === 'button';
    if (!fromButton) {
      return getShareMessage(detectShareLocale(), '/pages/today/index');
    }

    const label = (this.data.signalLabel as string) || '';
    const subtitle = (this.data.signalSubtitle as string) || '';
    if (!label) {
      return getShareMessage(detectShareLocale(), '/pages/today/index');
    }
    const locale = detectShareLocale();
    const lead = locale === 'zh' ? '今日训练信号' : 'Today';
    const title = subtitle ? `${lead}: ${label} — ${subtitle}` : `${lead}: ${label}`;
    return buildShareMessage(title, '/pages/today/index');
  },

  onShareTimeline() {
    const label = (this.data.signalLabel as string) || '';
    const subtitle = (this.data.signalSubtitle as string) || '';
    const locale = detectShareLocale();
    const fallback =
      locale === 'zh' ? '像专业选手一样训练，无论水平高低。' : 'Train like a pro. Whatever your level.';
    const title = label
      ? subtitle
        ? `${label} — ${subtitle}`
        : label
      : fallback;
    return buildTimelineMessage(title);
  },

  onScrollRefresh() {
    // Skyline pull-to-refresh fires on the scroll-view, not the page.
    // We mirror Webview's onPullDownRefresh semantics: refetch and let
    // the refresher unwind once the data settles.
    this.setData({ refreshing: true });
    void this.refetch().finally(() => this.setData({ refreshing: false }));
  },

  onRetry() {
    void this.refetch();
  },

  noop() { /* backdrop catchtap — prevents overlay close when tapping the card */ },

  onShareCardToggle() {
    const nextVisible = !this.data.shareCardVisible;
    // Invalidate the cached image if the theme changed since last render.
    const themeChanged = this.data.shareCardTheme !== '' && this.data.shareCardTheme !== this.data.chartTheme;
    if (themeChanged) {
      this.setData({ shareImagePath: '', shareCardTheme: '' });
    }
    this.setData({ shareCardVisible: nextVisible });
    if (nextVisible && !this.data.shareImagePath) {
      void this.renderShareCard();
    }
  },

  async renderShareCard() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const response = (this as unknown as Record<string, any>)._todayResponse;
    if (!response) return;
    const theme = this.data.chartTheme;
    const meta = signalMeta()[response.signal?.recommendation] ?? signalMeta().follow_plan;
    // Prefer the Coach headline when a receipt is rendering — otherwise
    // the on-screen narrative and the screenshot would carry different
    // sentences for the same signal. Falls through to the rule-based
    // reason when no receipt (LLM disabled, transient failure).
    const coach = this.data.coach;
    const shareReason = coach?.headline || response.signal?.reason || '';
    try {
      const path = await generateShareCard({
        label: meta.label,
        subtitle: meta.subtitle,
        reason: shareReason,
        color: meta.color,
        locale: detectShareLocale(),
        theme,
      });
      this.setData({ shareImagePath: path, shareCardTheme: theme });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[today] share card render failed:', e);
      this.setData({ shareCardVisible: false });
    }
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      // The brief endpoint normally returns `{ insight: null }` when
      // LLM is disabled — `.catch` here protects against a real
      // transport / 5xx failure (which the rule-based signal.reason
      // covers as deterministic fallback). Logged so a broken
      // /api/insights/daily_brief is observable in WeChat DevTools
      // and 实时日志 instead of silently regressing the receipt.
      const [response, insight] = await Promise.all([
        apiGet<TodayResponse>('/api/today'),
        fetchInsight('daily_brief').catch((e) => {
          // eslint-disable-next-line no-console
          console.warn('[today] daily brief fetch failed; falling back to rule-based reason:', e);
          return null;
        }),
      ]);
      // Cache raw response so renderShareCard can access it on first FAB tap.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (this as unknown as Record<string, any>)._todayResponse = response;
      this.setData(
        buildRenderState(response, this.data.themeClass, this.data.today, insight) as Record<string, unknown>,
      );
      // Share card is rendered lazily on first FAB tap. Clear any stale
      // path so the old signal's card doesn't show for the new signal.
      this.setData({ shareImagePath: '', shareCardVisible: false });
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') {
        this.setData({ loading: false });
        return;
      }
      const detail = err?.detail ?? String(e);
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },
});
