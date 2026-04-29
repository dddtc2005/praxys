import type { IAppOption } from '../../app';
import { apiGet } from '../../utils/api-client';
import { generateShareCard } from '../../utils/share-image';
import type { ApiError } from '../../utils/api-client';
import type { TodayResponse } from '../../types/api';
import { formatDistance, formatTime } from '../../utils/format';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { t, detectLocale } from '../../utils/i18n';
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
// and mini.
const SIGNAL_META: Record<string, SignalMeta> = {
  follow_plan: { label: 'GO', subtitle: 'Follow Plan', color: 'green' },
  easy: { label: 'EASY', subtitle: 'Go Easy', color: 'amber' },
  modify: { label: 'MODIFY', subtitle: 'Adjust Workout', color: 'amber' },
  reduce_intensity: { label: 'CAUTION', subtitle: 'Reduce Intensity', color: 'amber' },
  rest: { label: 'REST', subtitle: 'Recovery Day', color: 'red' },
};

/**
 * Map a TSB value to a textual zone name + accent class. Banister-style
 * bands; the science page is authoritative on exact zone boundaries for
 * whichever load theory is active. The web app's FormSparkline uses the
 * same buckets so this stays in sync.
 */
function tsbZone(tsb: number): { label: string; accent: string } {
  if (tsb > 25) return { label: 'Peaked', accent: 'ts-warning' };
  if (tsb >= 5) return { label: 'Fresh', accent: 'ts-primary' };
  if (tsb >= -10) return { label: 'Neutral', accent: '' };
  if (tsb >= -30) return { label: 'Fatigued', accent: 'ts-warning' };
  return { label: 'Over-fatigued', accent: 'ts-destructive' };
}

interface UpcomingRow {
  date: string;
  name: string;
  meta: string;
  hasMeta: boolean;
}

interface MetricRow {
  label: string;
  value: string;
}

interface SparklineSeries {
  label: string;
  color: string;
  values: (number | null)[];
  fill: boolean;
}

interface RenderState {
  themeClass: string;
  /** 'light' | 'dark' — narrow form passed to chart components. Derived
   *  from `themeClass` once on onLoad and updated whenever it changes. */
  chartTheme: 'light' | 'dark';
  today: string;
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;

  signalLabel: string;
  signalSubtitle: string;
  signalColor: 'green' | 'amber' | 'red';
  signalReason: string;

  hasSparkline: boolean;
  sparklineDates: string[];
  sparklineSeries: SparklineSeries[];
  formTsbHasValue: boolean;
  formTsbValue: string;
  formTsbZone: string;
  formTsbZoneAccent: string;

  recoveryStatus: string;
  recoveryHrv: string;
  recoveryRhr: string;
  recoverySleep: string;

  hasUpcoming: boolean;
  upcomingRows: UpcomingRow[];

  hasLastActivity: boolean;
  lastDate: string;
  lastMetrics: MetricRow[];

  // Weekly Load mini-card (web parity, issue #76).
  hasWeekLoad: boolean;
  weekLoadLabel: string;
  weekLoadActual: string;
  weekLoadPlannedSuffix: string;
  weekLoadHasPlanned: boolean;
  weekLoadHasPct: boolean;
  weekLoadPct: string;
  weekLoadPctAccent: string;
  weekLoadBarPct: number;
  weekLoadBarAccent: string;

  hasWarnings: boolean;
  warnings: string[];
}

function buildRenderState(response: TodayResponse | null, themeClass: string, today: string): Partial<RenderState> {
  if (!response) {
    return {};
  }

  const meta = SIGNAL_META[response.signal.recommendation] ?? SIGNAL_META.follow_plan;

  const sparkline = response.tsb_sparkline;
  const hasSparkline = sparkline != null && sparkline.values.length >= 2;
  const sparklineSeries: SparklineSeries[] = hasSparkline
    ? [
        {
          label: 'TSB',
          color: '#3b82f6',
          values: sparkline.values,
          fill: true,
        },
      ]
    : [];
  const tsbForHeadline =
    response.signal?.recovery?.tsb ??
    (hasSparkline ? sparkline.values[sparkline.values.length - 1] ?? null : null);
  const tsbZoneInfo = tsbForHeadline != null ? tsbZone(tsbForHeadline) : null;

  const rec = response.recovery_analysis;
  const recoveryStatus = rec?.status ?? '—';
  const recoveryHrv = rec?.hrv?.today_ms != null ? `${rec.hrv.today_ms.toFixed(0)} ms` : '—';
  const recoveryRhr = rec?.resting_hr != null ? `${rec.resting_hr.toFixed(0)} bpm` : '—';
  const recoverySleep = rec?.sleep_score != null ? `${rec.sleep_score.toFixed(0)}/100` : '—';

  const upcomingRows: UpcomingRow[] = (response.upcoming ?? []).slice(0, 3).map((w) => ({
    date: w.date,
    name: w.workout_type,
    meta: w.duration_min != null ? `${w.duration_min} min` : '',
    hasMeta: w.duration_min != null,
  }));

  const last = response.last_activity;
  const lastMetrics: MetricRow[] = [];
  if (last?.distance_km != null) {
    lastMetrics.push({ label: t('Distance'), value: formatDistance(last.distance_km) });
  }
  if (last?.duration_sec != null) {
    lastMetrics.push({ label: t('Duration'), value: formatTime(last.duration_sec) });
  }
  if (last?.avg_power != null) {
    lastMetrics.push({ label: t('Avg power'), value: `${last.avg_power.toFixed(0)} W` });
  }

  const warnings = response.warnings ?? [];

  // Weekly Load mini — mirrors web/src/components/WeeklyLoadMini.tsx.
  // Compliance bands: <70% under, >120% over, else on target. Color
  // applies to both the percentage label and the progress bar fill.
  const weekLoad = response.week_load;
  const hasWeekLoad = weekLoad != null;
  const wlActual = weekLoad ? Math.round(weekLoad.actual) : 0;
  const wlPlanned = weekLoad?.planned;
  const wlPct =
    wlPlanned != null && wlPlanned > 0 ? Math.round((wlActual / wlPlanned) * 100) : null;
  let wlAccent = 'ts-primary';
  if (wlPct != null) {
    if (wlPct > 120) wlAccent = 'ts-destructive';
    else if (wlPct < 70) wlAccent = 'ts-warning';
  }

  return {
    themeClass,
    today,
    loading: false,
    errorMessage: '',
    hasResponse: true,

    signalLabel: meta.label,
    signalSubtitle: meta.subtitle,
    signalColor: meta.color,
    signalReason: response.signal.reason,

    hasSparkline,
    sparklineDates: hasSparkline ? sparkline.dates : [],
    sparklineSeries,
    formTsbHasValue: tsbForHeadline != null,
    formTsbValue:
      tsbForHeadline != null
        ? `${tsbForHeadline >= 0 ? '+' : ''}${tsbForHeadline.toFixed(1)}`
        : '',
    formTsbZone: tsbZoneInfo?.label ?? '',
    formTsbZoneAccent: tsbZoneInfo?.accent ?? '',

    recoveryStatus,
    recoveryHrv,
    recoveryRhr,
    recoverySleep,

    hasUpcoming: upcomingRows.length > 0,
    upcomingRows,

    hasLastActivity: last != null,
    lastDate: last?.date ?? '',
    lastMetrics,

    hasWeekLoad,
    weekLoadLabel: weekLoad?.week_label ?? '',
    weekLoadActual: `${wlActual}`,
    weekLoadHasPlanned: wlPlanned != null,
    weekLoadPlannedSuffix:
      wlPlanned != null ? `/ ${Math.round(wlPlanned)} RSS` : 'No planned load this week',
    weekLoadHasPct: wlPct != null,
    weekLoadPct: wlPct != null ? `${wlPct}%` : '',
    weekLoadPctAccent: wlAccent,
    weekLoadBarPct: wlPct != null ? Math.min(wlPct, 100) : 0,
    weekLoadBarAccent: wlAccent,

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
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    noDataYet: t('No data available yet.'),
    formTsb: t('Form (TSB)'),
    noTsbData: t('No TSB data yet'),
    recovery: t('Recovery'),
    status: t('Status'),
    hrv: t('HRV'),
    restingHr: t('Resting HR'),
    sleep: t('Sleep'),
    weeklyLoad: t('Weekly Load'),
    noPlannedLoad: t('No planned load this week'),
    upcomingWorkouts: t('Upcoming workouts'),
    lastActivity: t('Last activity'),
    distance: t('Distance'),
    duration: t('Duration'),
    avgPower: t('Avg power'),
    warnings: t('Warnings'),
    longPressToShare: t('Long press to save & share'),
    close: t('Close'),
  };
}

interface RefreshState {
  refreshing: boolean;
  /** Whether the share card image is currently shown. Toggled by the
   *  FAB — the card only appears on demand, not on every page load. */
  shareCardVisible: boolean;
  shareImagePath: string;
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

  hasSparkline: false,
  sparklineDates: [],
  sparklineSeries: [],
  formTsbHasValue: false,
  formTsbValue: '',
  formTsbZone: '',
  formTsbZoneAccent: '',

  recoveryStatus: '—',
  recoveryHrv: '—',
  recoveryRhr: '—',
  recoverySleep: '—',

  hasUpcoming: false,
  upcomingRows: [],

  hasLastActivity: false,
  lastDate: '',
  lastMetrics: [],

  hasWeekLoad: false,
  weekLoadLabel: '',
  weekLoadActual: '',
  weekLoadPlannedSuffix: '',
  weekLoadHasPlanned: false,
  weekLoadHasPct: false,
  weekLoadPct: '',
  weekLoadPctAccent: '',
  weekLoadBarPct: 0,
  weekLoadBarAccent: '',

  hasWarnings: false,
  warnings: [],

  shareImagePath: '',
  shareCardVisible: false,
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
    applyThemeChrome();
    const tabBar = (this as { getTabBar?: () => { setData: (d: unknown) => void } | null })
      .getTabBar?.();
    tabBar?.setData({ selected: 0 });
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
    this.setData({ shareCardVisible: nextVisible });
    if (nextVisible && !this.data.shareImagePath) {
      void this.renderShareCard();
    }
  },

  async renderShareCard() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const response = (this as unknown as Record<string, any>)._todayResponse;
    if (!response) return;
    const meta = SIGNAL_META[response.signal?.recommendation] ?? SIGNAL_META.follow_plan;
    try {
      const path = await generateShareCard({
        label: meta.label,
        subtitle: meta.subtitle,
        reason: response.signal?.reason ?? '',
        color: meta.color,
        locale: detectShareLocale(),
        theme: this.data.chartTheme, // 'light' | 'dark' — follows user's theme
      });
      this.setData({ shareImagePath: path });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[today] share card render failed:', e);
    }
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      const response = await apiGet<TodayResponse>('/api/today');
      // Cache raw response so renderShareCard can access it on first FAB tap.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (this as unknown as Record<string, any>)._todayResponse = response;
      this.setData(
        buildRenderState(response, this.data.themeClass, this.data.today) as Record<string, unknown>,
      );
      // Share card is rendered lazily on first FAB tap. Clear any stale
      // path so the old signal's card doesn't show for the new signal.
      this.setData({ shareImagePath: '', shareCardVisible: false });
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') return;
      const detail = err?.detail ?? String(e);
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },
});
