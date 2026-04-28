import { apiGet } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import type { TrainingResponse } from '../../types/api';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { t } from '../../utils/i18n';

function buildTrainingTr() {
  return {
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    noData: t(
      'No training data yet. Sync Garmin / Stryd from the web app (Settings → Sync) to populate this view.',
    ),
    volume: t('Volume'),
    criticalPower: t('Critical Power'),
    fitnessFatigue: t('Fitness & Fatigue'),
    consistency: t('Consistency'),
    weeklyCompliance: t('Weekly Load Compliance'),
    findings: t('Findings'),
    suggestions: t('Suggestions'),
    plannedLabel: t('Planned'),
    actualLabel: t('Actual'),
  };
}
import {
  buildShareMessage,
  buildTimelineMessage,
  detectShareLocale,
  getShareMessage,
} from '../../utils/share';

interface ZoneRow {
  name: string;
  actualClamped: number;
  hasTarget: boolean;
  targetClamped: number;
  label: string;
}

interface FindingRow {
  className: string;
  message: string;
}

interface SuggestionRow {
  message: string;
}

interface SeriesPayload {
  label: string;
  color: string;
  values: (number | null)[];
  fill?: boolean;
}

interface TrainingState {
  themeClass: string;
  chartTheme: 'light' | 'dark';
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;
  hasAnyData: boolean;

  hasVolume: boolean;
  weeklyKm: string;
  hasVolumeTrend: boolean;
  volumeTrend: string;

  hasLatestCp: boolean;
  latestCpDisplay: string;
  cpDataPointCount: number;

  // Charts always render their card; sufficiency drives chart-vs-hint
  // swap inside. Mirrors web/src/pages/Training.tsx <DataHint> usage.
  cpSufficient: boolean;
  cpHintMessage: string;
  cpHintDetail: string;
  cpTrendDates: string[];
  cpTrendSeries: SeriesPayload[];

  ffSufficient: boolean;
  ffHintMessage: string;
  ffHintDetail: string;
  ffDates: string[];
  ffSeries: SeriesPayload[];

  hasDistribution: boolean;
  zoneSectionLabel: string;
  zoneRows: ZoneRow[];

  hasConsistency: boolean;
  consistencyLine: string;

  hasFindings: boolean;
  findings: FindingRow[];

  hasSuggestions: boolean;
  suggestions: SuggestionRow[];

  refreshing: boolean;

  // Sleep score vs Avg Power scatter (web parity, issue #76).
  sleepSufficient: boolean;
  sleepHintMessage: string;
  sleepHintDetail: string;
  sleepPerfTitle: string;
  sleepPerfYLabel: string;
  sleepPerfPairs: [number, number][];
  sleepPerfYIsPace: boolean;

  // Weekly compliance bars (web parity, issue #76).
  complianceSufficient: boolean;
  complianceHintMessage: string;
  complianceHintDetail: string;
  hasComplianceEstimateNote: boolean;
  complianceEstimateNote: string;
  complianceWeeks: string[];
  compliancePlanned: number[];
  complianceActual: number[];
  complianceActualColors: string[];
}

const initialData: TrainingState = {
  themeClass: 'theme-light',
  chartTheme: 'light',
  loading: true,
  errorMessage: '',
  hasResponse: false,
  hasAnyData: false,

  hasVolume: false,
  weeklyKm: '',
  hasVolumeTrend: false,
  volumeTrend: '',

  hasLatestCp: false,
  latestCpDisplay: '',
  cpDataPointCount: 0,

  cpSufficient: true,
  cpHintMessage: '',
  cpHintDetail: '',
  cpTrendDates: [],
  cpTrendSeries: [],

  ffSufficient: true,
  ffHintMessage: '',
  ffHintDetail: '',
  ffDates: [],
  ffSeries: [],

  hasDistribution: false,
  zoneSectionLabel: 'Zone distribution',
  zoneRows: [],

  hasConsistency: false,
  consistencyLine: '',

  hasFindings: false,
  findings: [],

  hasSuggestions: false,
  suggestions: [],

  refreshing: false,

  sleepSufficient: true,
  sleepHintMessage: '',
  sleepHintDetail: '',
  sleepPerfTitle: '',
  sleepPerfYLabel: '',
  sleepPerfPairs: [],
  sleepPerfYIsPace: false,

  complianceSufficient: true,
  complianceHintMessage: '',
  complianceHintDetail: '',
  hasComplianceEstimateNote: false,
  complianceEstimateNote: '',
  complianceWeeks: [],
  compliancePlanned: [],
  complianceActual: [],
  complianceActualColors: [],
};

function clampPct(v: number): number {
  return Math.max(0, Math.min(100, v));
}

function findingClassName(type: string | undefined): string {
  if (type === 'positive') return 'train-finding ts-primary';
  if (type === 'warning') return 'train-finding ts-warning';
  return 'train-finding';
}

// Compliance band colors (web parity): primary green = on target, warning
// amber = under, destructive red = over. Bands match ComplianceChart.tsx.
const COMPLIANCE_GREEN = '#00ff87';
const COMPLIANCE_AMBER = '#f59e0b';
const COMPLIANCE_RED = '#ef4444';

function complianceColor(planned: number | null, actual: number | null): string {
  if (planned == null || planned <= 0 || actual == null) return COMPLIANCE_GREEN;
  const pct = (actual / planned) * 100;
  if (pct < 80) return COMPLIANCE_AMBER;
  if (pct > 120) return COMPLIANCE_RED;
  return COMPLIANCE_GREEN;
}

function buildState(response: TrainingResponse, themeClass: string): Partial<TrainingState> {
  const { diagnosis, cp_trend, fitness_fatigue, sleep_perf, weekly_review, data_meta } = response;
  const weeklyKm = diagnosis?.volume?.weekly_avg_km;
  const hasVolume = typeof weeklyKm === 'number';
  const latestCp = cp_trend?.values?.length
    ? cp_trend.values[cp_trend.values.length - 1]
    : null;
  const distribution = diagnosis?.distribution ?? [];
  const consistency = diagnosis?.consistency;
  const findings = diagnosis?.diagnosis ?? [];
  const suggestions = diagnosis?.suggestions ?? [];
  const hasAnyData =
    hasVolume || latestCp != null || distribution.length > 0;

  // Sufficiency flags mirror web/src/pages/Training.tsx <DataHint> props.
  // Defaults to true when data_meta is missing so the charts attempt to
  // render — matches web behavior of `data_meta?.X ?? true`.
  const cpSufficient = data_meta?.cp_trend_sufficient ?? true;
  const ffSufficient = data_meta?.pmc_sufficient ?? true;
  const complianceSufficient = (data_meta?.data_days ?? 0) >= 14;
  const sleepSufficient = !!(
    data_meta?.has_recovery && (sleep_perf?.pairs?.length ?? 0) >= 2
  );

  const zoneRows: ZoneRow[] = distribution.map((z) => {
    const actual = z.actual_pct ?? 0;
    const target = z.target_pct;
    return {
      name: z.name,
      actualClamped: clampPct(actual),
      hasTarget: target != null,
      targetClamped: target != null ? clampPct(target) : 0,
      label: `${actual.toFixed(0)}%${target != null ? ` / ${target.toFixed(0)}%` : ''}`,
    };
  });

  const consistencyLine = consistency
    ? `${consistency.total_sessions ?? 0} sessions · gaps ≥7d: ${
        consistency.weeks_with_gaps ?? 0
      } · longest: ${consistency.longest_gap_days ?? 0}d`
    : '';

  return {
    themeClass,
    loading: false,
    errorMessage: '',
    hasResponse: true,
    hasAnyData,

    hasVolume,
    weeklyKm: hasVolume ? `${(weeklyKm as number).toFixed(1)} km/week` : '',
    hasVolumeTrend: !!diagnosis?.volume?.trend,
    volumeTrend: diagnosis?.volume?.trend ? `trend: ${diagnosis.volume.trend}` : '',

    hasLatestCp: latestCp != null,
    latestCpDisplay: latestCp != null ? `${latestCp.toFixed(0)} W` : '',
    cpDataPointCount: cp_trend?.values?.length ?? 0,

    cpSufficient,
    cpHintMessage: 'Not enough data to show CP trend',
    cpHintDetail: 'Need at least 3 activities with power data to plot a meaningful trend.',
    cpTrendDates: cp_trend?.dates ?? [],
    cpTrendSeries: cp_trend
      ? [{ label: 'CP', color: '#00ff87', values: cp_trend.values, fill: true }]
      : [],

    ffSufficient,
    ffHintMessage: 'Not enough data for accurate fitness tracking',
    ffHintDetail:
      'Sync at least 6 weeks of activity data to see meaningful fitness, fatigue, and form curves.',
    ffDates: fitness_fatigue?.dates ?? [],
    ffSeries: fitness_fatigue
      ? [
          { label: 'Fitness (CTL)', color: '#00ff87', values: fitness_fatigue.ctl },
          { label: 'Fatigue (ATL)', color: '#ef4444', values: fitness_fatigue.atl },
          { label: 'Form (TSB)', color: '#3b82f6', values: fitness_fatigue.tsb },
        ]
      : [],

    hasDistribution: zoneRows.length > 0,
    zoneSectionLabel: diagnosis?.theory_name
      ? `Zone distribution · ${diagnosis.theory_name}`
      : 'Zone distribution',
    zoneRows,

    hasConsistency: consistency != null,
    consistencyLine,

    hasFindings: findings.length > 0,
    findings: findings.map((f) => ({
      className: findingClassName(f.type),
      message: `• ${f.message}`,
    })),

    hasSuggestions: suggestions.length > 0,
    suggestions: suggestions.map((s, i) => ({ message: `${i + 1}. ${s}` })),

    // Sleep score vs metric scatter. Sufficiency mirrors web's check:
    // requires recovery data + at least 2 pairs to be meaningful.
    sleepSufficient,
    sleepHintMessage: 'Not enough data to show sleep vs performance',
    sleepHintDetail:
      'Sync activities together with sleep data (Garmin, Oura, or similar) so we can pair them by date.',
    sleepPerfTitle: sleep_perf?.metric_label
      ? `Sleep Score vs ${sleep_perf.metric_label}`
      : 'Sleep Score vs Avg Power',
    sleepPerfYLabel: sleep_perf
      ? `${sleep_perf.metric_label || 'Avg Power'} (${sleep_perf.metric_unit || 'W'})`
      : '',
    sleepPerfPairs: sleep_perf?.pairs ?? [],
    sleepPerfYIsPace: sleep_perf?.metric_unit === 'sec/km',

    // Weekly compliance bars. Web threshold: 14 days of data.
    complianceSufficient,
    complianceHintMessage: 'Not enough data for weekly load comparison',
    complianceHintDetail:
      'Sync at least 2 weeks of data to compare planned vs actual training load.',
    hasComplianceEstimateNote: !!weekly_review?.planned_estimated,
    complianceEstimateNote:
      'Planned bars are estimated — your plan has no RSS targets for this base.',
    complianceWeeks: weekly_review?.weeks ?? [],
    compliancePlanned: weekly_review?.planned_load ?? [],
    complianceActual: weekly_review?.actual_load ?? [],
    complianceActualColors: weekly_review
      ? weekly_review.weeks.map((_, i) =>
          complianceColor(
            weekly_review.planned_load?.[i] ?? null,
            weekly_review.actual_load?.[i] ?? null,
          ),
        )
      : [],
  };
}

Page({
  data: { ...initialData, tr: buildTrainingTr() },

  onLoad() {
    const tc = themeClassName();
    this.setData({ themeClass: tc, chartTheme: tc === 'theme-light' ? 'light' : 'dark' });
    void this.refetch();
  },

  onShow() {
    applyThemeChrome();
    const tabBar = (this as { getTabBar?: () => { setData: (d: unknown) => void } | null })
      .getTabBar?.();
    tabBar?.setData({ selected: 1 });
  },

  onShareAppMessage() {
    const cp = (this.data.latestCpDisplay as string) || '';
    const km = (this.data.weeklyKm as string) || '';
    const locale = detectShareLocale();
    if (cp && km) {
      const lead = locale === 'zh' ? '本周训练' : 'Training';
      return buildShareMessage(`${lead}: ${cp} CP · ${km}`, '/pages/training/index');
    }
    return getShareMessage(locale, '/pages/training/index');
  },

  onShareTimeline() {
    const cp = (this.data.latestCpDisplay as string) || '';
    const km = (this.data.weeklyKm as string) || '';
    const locale = detectShareLocale();
    const fallback =
      locale === 'zh' ? '像专业选手一样训练' : 'Train like a pro. Whatever your level.';
    return buildTimelineMessage(cp && km ? `${cp} CP · ${km}` : fallback);
  },

  onScrollRefresh() {
    this.setData({ refreshing: true });
    void this.refetch().finally(() => this.setData({ refreshing: false }));
  },

  onRetry() {
    void this.refetch();
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      const response = await apiGet<TrainingResponse>('/api/training');
      this.setData(buildState(response, this.data.themeClass) as Record<string, unknown>);
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') return;
      const detail = err?.detail ?? String(e);
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },
});
