import { setTabBarSelected } from '../../utils/tabbar';
import type { IAppOption } from '../../app';
import { apiGet } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import type {
  AiInsight,
  AiInsightFinding,
  InsightFeedbackVote,
  TrainingResponse,
} from '../../types/api';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { detectLocale, t, tFmt, tNamed } from '../../utils/i18n';
import { coachToggleLabel, fetchInsight, insightFeedbackState, localizedInsight } from '../../utils/insights';
import {
  buildShareMessage,
  buildTimelineMessage,
  detectShareLocale,
  getShareMessage,
} from '../../utils/share';
import {
  buildHeatAdaptationView,
  emptyHeatAdaptationView,
  HEAT_HISTORY_SCROLL_KEY,
  HEAT_HISTORY_SCROLL_TARGET,
  type HeatAdaptationView,
  type HeatSessionRow,
} from '../../utils/heat-adaptation';

type TrainingMetricId = 'tsb' | 'dist' | 'load' | 'volume' | 'heat';

function isTrainingMetricId(value: string): value is TrainingMetricId {
  return value === 'tsb'
    || value === 'dist'
    || value === 'load'
    || value === 'volume'
    || value === 'heat';
}

function buildTrainingTr() {
  return {
    navTitle: t('Training'),
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    noData: t(
      'No training data yet. Sync Garmin / Stryd from the web app (Settings → Sync) to populate this view.',
    ),

    // Diagnosis section eyebrow.
    diagnosis: t('Diagnosis'),

    // Peer metric index.
    peerMetrics: t('Peer metrics'),
    peerMetricsHint: t('Select a metric to inspect its chart or evidence.'),
    details: t('Details'),
    statTsbLabel: t('TSB'),
    statTsbSubPositive: t('long-term load above recent load'),
    statTsbSubBalanced: t('modeled loads balanced'),
    statTsbSubNegative: t('recent load above long-term load'),
    statTsbSubDefault: t('modeled balance (CTL−ATL)'),
    statDistLabel: t('Distribution match'),
    statDistSubDefault: t('vs target zones'),
    statLoadLabel: t('Load compliance'),
    statLoadSub: t('actual vs planned, avg'),
    statVolumeLabel: t('Volume'),
    statVolumeUnit: t('km/wk'),

    tsbDetailTitle: t('Load balance'),
    tsbDetailDescription: t(
      'Long-term load, recent load, and their modeled balance over time.',
    ),
    tsbMethodology: t(
      'CTL models longer-term training load, ATL models recent training load, and TSB is their difference. These are load-model estimates, not direct measures of recovery or readiness.',
    ),
    distributionDetailTitle: t('Zone distribution'),
    distributionDetailDescription: t(
      'Observed time in each intensity zone compared with the selected training theory.',
    ),
    loadDetailTitle: t('Load compliance'),
    loadDetailDescription: t(
      'Actual and planned weekly load across the recent training window.',
    ),
    volumeDetailTitle: t('Weekly volume'),
    volumeDetailDescription: t(
      'Recorded distance in non-overlapping seven-day buckets, including weeks with no recorded distance.',
    ),

    // Insufficient-data hints. Web's PR #280 introduced countdown
    // copy ("Need N more days") so the user knows when the chart
    // will become useful. Mini program inherits the same threshold.
    pmcMessage: t('Not enough data yet for stable load tracking'),
    loadMessage: t('Not enough data yet for weekly load comparison'),
    distributionMessage: t('Not enough complete intensity data for zone comparison'),
    distributionHint: t(
      'Sync split or sample data with enough duration coverage to compare against the selected theory.',
    ),
    volumeMessage: t('No weekly distance history yet'),
    volumeHint: t('Sync recent activities to populate the weekly distance series.'),
    volumePendingMessage: t('Weekly chart temporarily unavailable'),
    volumePendingHint: t(
      'The weekly history will appear after the data service update completes.',
    ),

    // Compliance bar legend.
    plannedLabel: t('Planned'),
    actualLabel: t('Actual'),
    zoneMethodology: t(
      'Distribution match uses Bray-Curtis similarity to compare observed and target time-in-zone shares. It appears only when every recent activity has at least 90% duration coverage from valid splits or timestamped samples; sample streams also require a median cadence of 5 seconds or less. These evidence gates are Praxys operational estimates.',
    ),
    complianceMethodology: t(
      'Compliance is the mean weekly actual-to-planned load ratio across completed weeks where actual and planned load both use exact selected-base inputs and the plan target is positive. Estimated weeks stay in the chart but are excluded from the summary. This is an execution comparison, not a quality, safety, recovery, or readiness score.',
    ),
    volumeMethodology: t(
      'Each value is a non-overlapping seven-day bucket ending on the shown date. Weeks with no recorded distance remain in the series and average. Trend labels use a Praxys estimate: the newer half must differ from the older half by more than 10%; this is not a readiness score.',
    ),
    distanceUnit: t('km'),
    weeklyAverage: t('Weekly average'),
    weeklyValues: t('Weekly values'),
    trend: t('Trend'),

    // Coach receipt fallback strings.
    weeklyReady: t('Weekly diagnosis ready.'),
    findings: t('Findings'),
    recommendations: t('Recommendations'),
    coachMark: t('Praxys Coach'),
    coachAria: t('Praxys Coach insight'),
  };
}

// ---- Praxys Coach receipt (training_review) ----
//
// Same shape used by deterministic Today guidance and Goal (race_forecast). On
// the new Training page (web PR #280) the receipt is always rendered:
// when an LLM `training_review` row exists it carries the AI content;
// when not, the rule-based diagnosis prose populates the same shape so
// the narrative-led layout persists with or without AI.

type CoachMarker = '[+]' | '[!]' | '[·]';

interface CoachFindingRow {
  /** Stable unique key for `wx:key` — array index, not text, because
   *  two findings can carry identical copy (e.g. repeated neutral
   *  notes across reviews) and Skyline's reconciler would collide on
   *  duplicate keys. */
  id: string;
  marker: CoachMarker;
  tone: AiInsightFinding['type'];
  text: string;
}

interface CoachRecRow {
  /** 1-based ordinal as a string for WXML rendering and `wx:key`. */
  index: string;
  text: string;
}

interface CoachReceipt {
  /** "2h ago" / "5分钟前" for AI rows; "6wk" for rule-based fallback
   *  (mirrors the lookback window used by the diagnosis). Empty
   *  string hides the chip. */
  stamp: string;
  headline: string;
  hasFindings: boolean;
  findings: CoachFindingRow[];
  hasRecommendations: boolean;
  recommendations: CoachRecRow[];
}

interface CoachTranslations {
  mark: string;
  findings: string;
  recommendations: string;
  aria: string;
}

function timeAgo(isoDate: string, locale: 'en' | 'zh'): string {
  try {
    const diff = Date.now() - new Date(isoDate).getTime();
    const rtf = new Intl.RelativeTimeFormat(
      locale === 'zh' ? 'zh-CN' : 'en-US',
      { style: 'short' },
    );
    const mins = Math.floor(diff / 60_000);
    if (mins < 60) return rtf.format(-mins, 'minute');
    const hours = Math.floor(mins / 60);
    if (hours < 24) return rtf.format(-hours, 'hour');
    const days = Math.floor(hours / 24);
    return rtf.format(-days, 'day');
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[training] timeAgo failed; dropping stamp:', isoDate, e);
    return '';
  }
}

function markerFor(type: AiInsightFinding['type']): CoachMarker {
  return type === 'positive' ? '[+]' : type === 'warning' ? '[!]' : '[·]';
}

function buildCoachFromInsight(
  insight: AiInsight,
  locale: 'en' | 'zh',
): CoachReceipt {
  const view = localizedInsight(insight, locale);
  const findings: CoachFindingRow[] = view.findings.map((f, i) => ({
    id: `${i}`,
    marker: markerFor(f.type),
    tone: f.type,
    text: f.text,
  }));
  const recommendations: CoachRecRow[] = view.recommendations.map((r, i) => ({
    index: `${i + 1}`,
    text: r,
  }));
  return {
    stamp: insight.generated_at ? timeAgo(insight.generated_at, locale) : '',
    headline: view.headline,
    hasFindings: findings.length > 0,
    findings,
    hasRecommendations: recommendations.length > 0,
    recommendations,
  };
}


/**
 * Rule-based fallback Coach Receipt — used when no LLM
 * `training_review` row exists. The API's diagnosis and suggestions
 * remain the single source of rule-based interpretation.
 *
 * The receipt always renders something: even with zero rule findings
 * and zero deviations, the headline is "Weekly diagnosis ready." so
 * the narrative-led layout survives blank-data accounts. The user
 * then reads the stat strip + chart for context.
 */
function buildCoachFallback(
  diagnosis: TrainingResponse['diagnosis'],
  locale: 'en' | 'zh',
): CoachReceipt {
  const ruleFindings = diagnosis?.diagnosis ?? [];
  const ruleSuggestions = diagnosis?.suggestions ?? [];
  const findings: CoachFindingRow[] = ruleFindings.map((finding, i) => ({
    id: `rule-${i}`,
    marker: markerFor(finding.type),
    tone: finding.type,
    text: finding.message,
  }));
  const recommendations: CoachRecRow[] = ruleSuggestions.map((suggestion, i) => ({
    index: `${i + 1}`,
    text: suggestion,
  }));

  // Lead-finding-as-headline. Prefer warnings (most actionable),
  // then positives, then the first rule finding, then the default.
  const lead =
    ruleFindings.find((f) => f.type === 'warning') ??
    ruleFindings.find((f) => f.type === 'positive') ??
    ruleFindings[0];
  const headline = lead?.message ?? t('Weekly diagnosis ready.');

  // Stamp is the lookback window (e.g. "6wk") rather than a relative
  // age — rule-based content is always "now", so a timeAgo stamp
  // would say "0 minutes ago" misleadingly.
  const lookback = diagnosis?.lookback_weeks;
  const stamp = lookback ? `${lookback}wk` : '';

  // Suppress the locale param: rule-based prose is single-language
  // (the diagnosis route emits whichever language the user chose at
  // sync time). The `locale` param is here for symmetry with
  // `buildCoachFromInsight` — if the route is later split, we'll
  // thread it through the markerFor / tFmt path.
  void locale;

  return {
    stamp,
    headline,
    hasFindings: findings.length > 0,
    findings,
    hasRecommendations: recommendations.length > 0,
    recommendations,
  };
}

interface ZoneRow {
  name: string;
  actualClamped: number;
  hasTarget: boolean;
  targetClamped: number;
  label: string;

}

interface SeriesPayload {
  label: string;
  color: string;
  values: (number | null)[];
  fill?: boolean;
}

interface StatCell {
  id: TrainingMetricId;
  anchorId: string;
  label: string;
  value: string;
  sub: string;

  /** `%` suffix shown only for compliance/match cells. Composes with
   *  the value as `{value}{unit}` so ts-value can keep tabular-nums. */
  unit: string;
}

interface TrainingState {
  themeClass: string;
  chartTheme: 'light' | 'dark';
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;
  hasAnyData: boolean;

  /** "Last N weeks" eyebrow, e.g. "Last 6 weeks" / "近 6 周". */
  diagnosisEyebrow: string;

  cells: StatCell[];
  heat: HeatAdaptationView;
  activeMetric: TrainingMetricId | '';
  metricSheetTitle: string;
  metricSheetDescription: string;
  expandedHeatSessionId: string;
  selectedHeatDayId: string;
  selectedHeatDayDetail: string;
  selectedHeatDayHasEvidence: boolean;
  selectedHeatSessions: HeatSessionRow[];
  scrollIntoView: string;

  /** True iff the response contains complete zone targets to render. */
  hasZones: boolean;

  // Form (Fitness/Fatigue) chart.
  ffSufficient: boolean;
  ffHintMessage: string;
  ffHintDetail: string;
  ffDates: string[];
  ffSeries: SeriesPayload[];

  // Zone distribution.
  zoneSectionLabel: string;
  zoneRows: ZoneRow[];

  // Compliance bars.
  complianceSufficient: boolean;
  complianceHintMessage: string;
  complianceHintDetail: string;
  hasComplianceEstimateNote: boolean;
  complianceEstimateNote: string;
  complianceWeeks: string[];
  compliancePlanned: number[];
  complianceActual: number[];
  complianceEstimated: boolean[];

  // Weekly distance.
  volumeSufficient: boolean;
  volumeHintMessage: string;
  volumeHintDetail: string;
  volumeSummary: string;
  volumeTrend: string;
  volumeDates: string[];
  volumeKm: number[];
  volumePoints: Array<{ id: string; week: string; distance: string }>;

  // Coach Receipt — always populated (LLM if present, rule-based
  // fallback otherwise). Web Training never nil-renders the receipt
  // on the new page; mini matches.
  coach: CoachReceipt;
  coachTr: CoachTranslations;
  /** Findings + recommendations are progressively disclosed; default
   *  collapsed so the receipt reads as headline-first. The user opts
   *  in to the structured detail. Mirrors web's AiInsightsCard. */
  detailsOpen: boolean;
  /** Pre-computed toggle button label — `{N} findings · {M} recs` when
   *  collapsed, "Hide details" when expanded. Empty string hides the
   *  toggle entirely (zero findings + zero recs). */
  coachToggleLabel: string;
  coachDatasetHash: string;
  coachFeedbackVote: InsightFeedbackVote | '';

  refreshing: boolean;
}

const initialData: TrainingState = {
  themeClass: getApp<IAppOption>().globalData.themeClass,
  chartTheme: 'light',
  loading: true,
  errorMessage: '',
  hasResponse: false,
  hasAnyData: false,

  diagnosisEyebrow: '',
  cells: [],
  heat: emptyHeatAdaptationView(),
  activeMetric: '',
  metricSheetTitle: '',
  metricSheetDescription: '',
  expandedHeatSessionId: '',
  selectedHeatDayId: '',
  selectedHeatDayDetail: '',
  selectedHeatDayHasEvidence: false,
  selectedHeatSessions: [],
  scrollIntoView: '',

  hasZones: false,

  ffSufficient: true,
  ffHintMessage: '',
  ffHintDetail: '',
  ffDates: [],
  ffSeries: [],

  zoneSectionLabel: '',
  zoneRows: [],

  complianceSufficient: true,
  complianceHintMessage: '',
  complianceHintDetail: '',
  hasComplianceEstimateNote: false,
  complianceEstimateNote: '',
  complianceWeeks: [],
  compliancePlanned: [],
  complianceActual: [],
  complianceEstimated: [],

  volumeSufficient: false,
  volumeHintMessage: '',
  volumeHintDetail: '',
  volumeSummary: '',
  volumeTrend: '',
  volumeDates: [],
  volumeKm: [],
  volumePoints: [],

  coach: {
    stamp: '',
    headline: '',
    hasFindings: false,
    findings: [],
    hasRecommendations: false,
    recommendations: [],
  },
  coachTr: { mark: '', findings: '', recommendations: '', aria: '' },
  detailsOpen: false,
  coachToggleLabel: '',
  coachDatasetHash: '',
  coachFeedbackVote: '',

  refreshing: false,
};

function clampPct(v: number): number {
  return Math.max(0, Math.min(100, v));
}


/**
 * Build the five peer-metric rows from the server-owned summary.
 * Values stay neutral because TSB and execution ratios are descriptive,
 * not physiological quality, safety, or readiness scores.
 */
function buildStatCells(
  response: TrainingResponse,
  tr: ReturnType<typeof buildTrainingTr>,
  heat: HeatAdaptationView,
): StatCell[] {
  const cells: StatCell[] = [];

  const tsbCurrent = response.summary.current_tsb;
  const tsbValue =
    tsbCurrent != null
      ? `${tsbCurrent >= 0 ? '+' : ''}${tsbCurrent.toFixed(1)}`
      : '—';
  let tsbSub = tr.statTsbSubDefault;
  if (tsbCurrent != null) {
    if (tsbCurrent > 0) {
      tsbSub = tr.statTsbSubPositive;
    } else if (tsbCurrent < 0) {
      tsbSub = tr.statTsbSubNegative;
    } else {
      tsbSub = tr.statTsbSubBalanced;
    }
  }
  cells.push({
    id: 'tsb',
    anchorId: 'metric-tsb',
    label: tr.statTsbLabel,
    value: tsbValue,
    sub: tsbSub,
    unit: '',
  });

  const distMatch = response.summary.distribution_match_pct;
  const theoryName = response.diagnosis?.theory_name;
  cells.push({
    id: 'dist',
    anchorId: 'metric-distribution',
    label: tr.statDistLabel,
    value: distMatch != null ? `${distMatch}` : '—',
    sub: theoryName
      ? tFmt('vs {0}', theoryName)
      : tr.statDistSubDefault,
    unit: distMatch != null ? '%' : '',
  });

  const loadCompliance = response.summary.load_compliance_pct;
  cells.push({
    id: 'load',
    anchorId: 'metric-load',
    label: tr.statLoadLabel,
    value: loadCompliance != null ? `${loadCompliance}` : '—',
    sub: tr.statLoadSub,
    unit: loadCompliance != null ? '%' : '',
  });

  // Volume — weekly average km. Foreground default tone (no verdict).
  const weeklyKm = response.diagnosis?.volume?.weekly_avg_km;
  const volumeAvailable = hasVolumeSummary(response.diagnosis?.volume);
  const lookback = response.diagnosis?.lookback_weeks ?? 0;
  cells.push({
    id: 'volume',
    anchorId: 'metric-volume',
    label: tr.statVolumeLabel,
    value: volumeAvailable && weeklyKm != null ? weeklyKm.toFixed(1) : '—',
    sub: tFmt('{0}-week average', lookback),
    unit: volumeAvailable ? tr.statVolumeUnit : '',
  });

  cells.push({
    id: 'heat',
    anchorId: HEAT_HISTORY_SCROLL_TARGET,
    label: heat.label,
    value: heat.metricValue,
    sub: heat.metricAction,
    unit: '',
  });

  return cells;
}

function metricSheetCopy(
  metric: TrainingMetricId | '',
  tr: ReturnType<typeof buildTrainingTr>,
  heat: HeatAdaptationView,
): { title: string; description: string } {
  if (metric === 'tsb') {
    return { title: tr.tsbDetailTitle, description: tr.tsbDetailDescription };
  }
  if (metric === 'dist') {
    return {
      title: tr.distributionDetailTitle,
      description: tr.distributionDetailDescription,
    };
  }
  if (metric === 'load') {
    return { title: tr.loadDetailTitle, description: tr.loadDetailDescription };
  }
  if (metric === 'volume') {
    return { title: tr.volumeDetailTitle, description: tr.volumeDetailDescription };
  }
  if (metric === 'heat') {
    return { title: heat.label, description: heat.conditionRange };
  }
  return { title: '', description: '' };
}

function hasVolumeSummary(
  volume: TrainingResponse['diagnosis']['volume'] | undefined,
): boolean {
  if (!volume) return false;
  return volume.weeks === undefined
    ? volume.weekly_avg_km > 0
    : volume.weeks.length > 0;
}

function formatVolumeWeek(value: string): string {
  const [year, month, day] = value.split('-').map(Number);
  if (!year || !month || !day) return value;
  return new Date(year, month - 1, day).toLocaleDateString(
    detectLocale() === 'zh' ? 'zh-CN' : 'en-US',
    { year: 'numeric', month: 'short', day: 'numeric' },
  );
}

function buildState(
  response: TrainingResponse,
  themeClass: string,
  insight: AiInsight | null,
  tr: ReturnType<typeof buildTrainingTr>,
  activeMetric: TrainingMetricId | '',
): Partial<TrainingState> {
  const { diagnosis, fitness_fatigue, weekly_review, data_meta } = response;
  const distribution = diagnosis?.distribution ?? [];
  const distributionAvailable = !!diagnosis && diagnosis.data_meta.distribution_complete;
  const hasZones =
    distributionAvailable && distribution.some((z) => z.target_pct != null);
  const dataDays = data_meta?.data_days ?? 0;
  const hasAnyData =
    hasVolumeSummary(diagnosis?.volume) ||
    (distributionAvailable && distribution.length > 0) ||
    (fitness_fatigue?.dates?.length ?? 0) > 0 ||
    response.heat_adaptation.sessions.length > 0;

  // Sufficiency — countdown copy mirrors web's PR #280 wording.
  const ffSufficient = data_meta?.pmc_sufficient ?? true;
  const loadTimeConstantDays = data_meta?.load_time_constant_days ?? 42;
  const daysToPmc = Math.max(0, loadTimeConstantDays - dataDays);
  const ffHintDetail = tNamed(
    'The active load model uses a {loadTimeConstantDays}-day long-term time constant. Need {daysToPmc} more days of history.',
    { loadTimeConstantDays, daysToPmc },
  );
  const complianceSufficient = dataDays >= 14;
  const daysToCompare = Math.max(0, 14 - dataDays);
  const complianceHintDetail = t(
    'Need 2 weeks of synced activity to compare planned vs actual. {daysToCompare} more days to go.',
  ).replace('{daysToCompare}', String(daysToCompare));

  const zoneRows: ZoneRow[] = (distributionAvailable ? distribution : []).map((z) => {
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

  // Coach receipt — always populated. AI takes precedence; rule-based
  // fallback when no LLM row, generation cap hit, or transient
  // /api/insights/training_review failure.
  const locale = detectLocale();
  let coach: CoachReceipt;
  let coachIsAi = false;
  if (insight) {
    try {
      coach = buildCoachFromInsight(insight, locale);
      coachIsAi = true;
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[training] AI receipt build failed; using rule-based fallback:', e);
      coach = buildCoachFallback(diagnosis, locale);
    }
  } else {
    coach = buildCoachFallback(diagnosis, locale);
  }
  const feedbackState = coachIsAi
    ? insightFeedbackState(insight)
    : { datasetHash: '', vote: '' as InsightFeedbackVote | '' };
  const coachDatasetHash = feedbackState.datasetHash;
  const coachFeedbackVote = feedbackState.vote;
  const coachTr: CoachTranslations = {
    mark: tr.coachMark,
    findings: tr.findings,
    recommendations: tr.recommendations,
    aria: tr.coachAria,
  };
  // Reset detailsOpen on every refetch — the receipt content has
  // changed (different findings / recs), so showing the prior
  // expanded state would surface a stale-looking detail block. Web's
  // AiInsightsCard re-mounts on refetch and naturally lands closed.
  const detailsOpen = false;
  const coachToggleLabelText = coachToggleLabel(
    coach.findings.length,
    coach.recommendations.length,
    detailsOpen,
  );

  const lookback = diagnosis?.lookback_weeks;
  const diagnosisEyebrow = lookback
    ? tFmt('Last {0} weeks', lookback)
    : tr.diagnosis;
  const heat = buildHeatAdaptationView(response.heat_adaptation);
  const defaultHeatDay = heat.cadenceDays.find((day) => day.id === heat.defaultCadenceId);
  const sheetCopy = metricSheetCopy(activeMetric, tr, heat);
  const volumeWeeks = diagnosis?.volume?.weeks ?? [];
  const volumeKm = diagnosis?.volume?.weekly_km ?? [];
  const volumeAverage = diagnosis?.volume?.weekly_avg_km ?? 0;
  const volumeSeriesPending = diagnosis?.volume != null && (
    diagnosis.volume.weeks === undefined || diagnosis.volume.weekly_km === undefined
  );
  const volumeSufficient = volumeWeeks.length > 0 && volumeWeeks.length === volumeKm.length;

  return {
    themeClass,
    loading: false,
    errorMessage: '',
    hasResponse: true,
    hasAnyData,

    diagnosisEyebrow,
    cells: buildStatCells(response, tr, heat),
    heat,
    activeMetric,
    metricSheetTitle: sheetCopy.title,
    metricSheetDescription: sheetCopy.description,
    expandedHeatSessionId: '',
    selectedHeatDayId: heat.defaultCadenceId,
    selectedHeatDayDetail: heat.defaultCadenceDetail,
    selectedHeatDayHasEvidence: defaultHeatDay?.hasEvidence ?? false,
    selectedHeatSessions: heat.sessions.filter((session) => session.dateKey === heat.defaultCadenceId),

    hasZones,

    ffSufficient,
    ffHintMessage: tr.pmcMessage,
    ffHintDetail,
    ffDates: fitness_fatigue?.dates ?? [],
    ffSeries: fitness_fatigue
      ? [
          { label: t('Long-term load (CTL)'), color: '#00ff87', values: fitness_fatigue.ctl },
          { label: t('Recent load (ATL)'), color: '#ef4444', values: fitness_fatigue.atl },
          { label: t('Load balance (TSB)'), color: '#3b82f6', values: fitness_fatigue.tsb },
        ]
      : [],

    zoneSectionLabel: diagnosis?.theory_name
      ? tFmt('{0} · {1}', t('Zone distribution'), diagnosis.theory_name)
      : t('Zone distribution'),
    zoneRows,

    complianceSufficient,
    complianceHintMessage: tr.loadMessage,
    complianceHintDetail,
    hasComplianceEstimateNote: !!(
      weekly_review?.actual_estimated || weekly_review?.planned_estimated
    ),
    complianceEstimateNote: t(
      'Bars marked with ~ use estimated load because selected-base activity or plan inputs are incomplete. Estimated weeks remain visible but are excluded from the summary.',
    ),
    complianceWeeks: weekly_review?.weeks ?? [],
    compliancePlanned: weekly_review?.planned_load ?? [],
    complianceActual: weekly_review?.actual_load ?? [],
    complianceEstimated: (weekly_review?.weeks ?? []).map(
      (_, index) => Boolean(
        weekly_review?.week_actual_estimated?.[index]
        || weekly_review?.week_planned_estimated?.[index],
      ),
    ),

    volumeSufficient,
    volumeHintMessage: volumeSeriesPending ? tr.volumePendingMessage : tr.volumeMessage,
    volumeHintDetail: volumeSeriesPending ? tr.volumePendingHint : tr.volumeHint,
    volumeSummary: tNamed('{lookback}-week average · {average} km/week', {
      lookback: diagnosis?.lookback_weeks ?? 0,
      average: volumeAverage.toFixed(1),
    }),
    volumeTrend: t(diagnosis?.volume?.trend ?? 'insufficient_data'),
    volumeDates: volumeWeeks,
    volumeKm,
    volumePoints: volumeSufficient
      ? volumeWeeks.map((week, index) => ({
          id: week,
          week: formatVolumeWeek(week),
          distance: `${volumeKm[index].toFixed(1)} ${tr.distanceUnit}`,
        }))
      : [],


    coach,
    coachTr,
    detailsOpen,
    coachToggleLabel: coachToggleLabelText,
    coachDatasetHash,
    coachFeedbackVote,
  };
}

function consumeHeatHistoryScrollRequest(): boolean {
  try {
    if (wx.getStorageSync<string>(HEAT_HISTORY_SCROLL_KEY) !== HEAT_HISTORY_SCROLL_TARGET) {
      return false;
    }
    wx.removeStorageSync(HEAT_HISTORY_SCROLL_KEY);
    return true;
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[training] could not consume heat-history scroll request:', e);
    return false;
  }
}

interface PageMethods extends WechatMiniprogram.IAnyObject {
  onOpenMetricDetail(e: WechatMiniprogram.TouchEvent): void;
  onCloseMetricDetail(): void;
  onBlockMetricSheetTap(): void;
  onPickHeatDay(e: WechatMiniprogram.TouchEvent): void;
  onToggleHeatSession(e: WechatMiniprogram.TouchEvent): void;
  onOpenHeatScience(): void;
  scrollToHeatIfPending(): void;
  onToggleCoachDetails(): void;
  onScrollRefresh(): void;
  onRetry(): void;
  refetch(options?: { background?: boolean }): Promise<void>;
}

Page<TrainingState & { tr: ReturnType<typeof buildTrainingTr> }, PageMethods>({
  data: { ...initialData, tr: buildTrainingTr() },

  onLoad() {
    const tc = themeClassName();
    this.setData({
      themeClass: tc,
      chartTheme: tc === 'theme-light' ? 'light' : 'dark',
      tr: buildTrainingTr(),
    });
    const pageState = this as unknown as Record<string, unknown>;
    pageState._locale = getApp<IAppOption>().globalData.locale;
    void this.refetch();
  },

  onShow() {
    const tc = themeClassName();
    if (tc !== this.data.themeClass) {
      this.setData({ themeClass: tc, chartTheme: tc === 'theme-light' ? 'light' : 'dark' });
    }
    const curLocale = getApp<IAppOption>().globalData.locale;
    const pgMut = this as unknown as Record<string, unknown>;
    const returningToTab = pgMut._hasShownOnce === true;
    pgMut._hasShownOnce = true;
    let localeChanged = false;
    if (curLocale !== pgMut._locale) {
      pgMut._locale = curLocale;
      localeChanged = true;
      this.setData({ tr: buildTrainingTr() });
    }
    if (returningToTab || localeChanged) {
      void this.refetch({ background: true });
    }
    if (consumeHeatHistoryScrollRequest()) {
      pgMut._scrollToHeatPending = true;
      this.scrollToHeatIfPending();
    }
    applyThemeChrome();
    setTabBarSelected(this, 1);
  },

  onShareAppMessage() {
    // Prefer the most actionable stat for the share blurb — TSB
    // changes daily, so it's the most "now" framing. Volume is the
    // weekly cadence number; both make recognizable share text.
    const cells = this.data.cells as StatCell[];
    const tsb = cells.find((c) => c.id === 'tsb');
    const vol = cells.find((c) => c.id === 'volume');
    const locale = detectShareLocale();
    if (tsb && vol && tsb.value !== '—' && vol.value !== '—') {
      const lead = locale === 'zh' ? '本周训练' : 'Training';
      return buildShareMessage(
        `${lead}: TSB ${tsb.value} · ${vol.value} km/wk`,
        '/pages/training/index',
      );
    }
    return getShareMessage(locale, '/pages/training/index');
  },

  onShareTimeline() {
    const cells = this.data.cells as StatCell[];
    const tsb = cells.find((c) => c.id === 'tsb');
    const vol = cells.find((c) => c.id === 'volume');
    const locale = detectShareLocale();
    const fallback =
      locale === 'zh'
        ? '像专业选手一样训练，无论水平高低。'
        : 'Train like a pro. Whatever your level.';
    return buildTimelineMessage(
      tsb && vol && tsb.value !== '—' && vol.value !== '—'
        ? `TSB ${tsb.value} · ${vol.value} km/wk`
        : fallback,
    );
  },

  onScrollRefresh() {
    this.setData({ refreshing: true });
    void this.refetch().finally(() => this.setData({ refreshing: false }));
  },

  onRetry() {
    void this.refetch();
  },

  onOpenMetricDetail(e: WechatMiniprogram.TouchEvent) {
    const metric = String(e.currentTarget.dataset.metric ?? '');
    if (!isTrainingMetricId(metric)) return;
    const copy = metricSheetCopy(metric, this.data.tr, this.data.heat);
    this.setData({
      activeMetric: metric,
      metricSheetTitle: copy.title,
      metricSheetDescription: copy.description,
    });
  },

  onCloseMetricDetail() {
    this.setData({
      activeMetric: '',
      metricSheetTitle: '',
      metricSheetDescription: '',
    });
  },

  onBlockMetricSheetTap() {
    // Prevent taps inside the sheet from reaching the dismiss backdrop.
  },

  onPickHeatDay(e: WechatMiniprogram.TouchEvent) {
    const id = String(e.currentTarget.dataset.id ?? '');
    const day = this.data.heat.cadenceDays.find((item) => item.id === id);
    if (!day) return;
    this.setData({
      selectedHeatDayId: day.id,
      selectedHeatDayDetail: day.detail,
      selectedHeatDayHasEvidence: day.hasEvidence,
      selectedHeatSessions: this.data.heat.sessions.filter((session) => session.dateKey === day.id),
      expandedHeatSessionId: '',
    });
  },

  onToggleHeatSession(e: WechatMiniprogram.TouchEvent) {
    const id = String(e.currentTarget.dataset.id ?? '');
    if (!id) return;
    this.setData({
      expandedHeatSessionId: this.data.expandedHeatSessionId === id ? '' : id,
    });
  },

  onOpenHeatScience() {
    wx.navigateTo({ url: '/pages/science/index?pillar=heat' }); // i18n-allow
  },

  scrollToHeatIfPending() {
    const pageState = this as unknown as Record<string, unknown>;
    if (pageState._scrollToHeatPending !== true || !this.data.hasResponse) return;
    pageState._scrollToHeatPending = false;
    const copy = metricSheetCopy('heat', this.data.tr, this.data.heat);
    this.setData({ scrollIntoView: '' }, () => {
      this.setData({
        scrollIntoView: HEAT_HISTORY_SCROLL_TARGET,
        activeMetric: 'heat',
        metricSheetTitle: copy.title,
        metricSheetDescription: copy.description,
      });
    });
  },

  /**
   * Tap-toggle the Coach Receipt's findings + recommendations details.
   * Recompute the toggle label so "{N} findings · {M} recs" flips to
   * "Hide details" (and vice versa) without a re-render of the rest
   * of the receipt body.
   */
  onToggleCoachDetails() {
    const next = !this.data.detailsOpen;
    const label = coachToggleLabel(
      this.data.coach.findings.length,
      this.data.coach.recommendations.length,
      next,
    );
    this.setData({ detailsOpen: next, coachToggleLabel: label });
  },

  onCoachFeedbackStale() {
    void this.refetch();
  },

  async refetch(options?: { background?: boolean }) {
    const pageState = this as unknown as Record<string, unknown>;
    const background = options?.background === true && this.data.hasResponse;
    const previousRequestId = typeof pageState._refetchRequestId === 'number'
      ? pageState._refetchRequestId
      : 0;
    const requestId = previousRequestId + 1;
    pageState._refetchRequestId = requestId;
    this.setData(background
      ? { errorMessage: '' }
      : { loading: true, errorMessage: '' });
    try {
      const [response, insight] = await Promise.all([
        apiGet<TrainingResponse>('/api/training'),
        fetchInsight('training_review').catch((e) => {
          // eslint-disable-next-line no-console
          console.warn('[training] training_review fetch failed; rule-based fallback active:', e);
          return null;
        }),
      ]);
      if (pageState._refetchRequestId !== requestId) return;
      this.setData(
        buildState(
          response,
          this.data.themeClass,
          insight,
          this.data.tr,
          this.data.activeMetric,
        ) as Record<string, unknown>,
        () => this.scrollToHeatIfPending(),
      );
    } catch (e) {
      if (pageState._refetchRequestId !== requestId) return;
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') {
        this.setData({ loading: false });
        return;
      }
      const detail = err?.detail ?? String(e);
      if (background) {
        // eslint-disable-next-line no-console
        console.warn('[training] background refresh failed; keeping cached response:', detail);
        return;
      }
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },
});
