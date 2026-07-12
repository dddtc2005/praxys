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

// Persisted active pill — same key web uses (mini program uses wx
// storage instead of localStorage, but the chosen value is portable).
const DIAGNOSIS_CHART_KEY = 'praxys.diagnosis_chart';

type DiagnosisPill = 'form' | 'zones' | 'compliance';

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

    // Stat strip — labels, sub-text, units. The four metrics answer
    // four distinct training questions: TSB (form), Distribution
    // (zone mix vs target), Load compliance (planned vs actual), and
    // Volume (amount of work). Strip order matches pill order so eye
    // → number → chart is one motion.
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

    // Pill switcher labels. Compact for the phone-width row; the
    // chart heading below carries the full context (e.g. the FF
    // chart still shows "Fitness · Fatigue · Form" as legend).
    pillForm: t('Load balance'),
    pillZones: t('Zones'),
    pillCompliance: t('Compliance'),

    // Insufficient-data hints. Web's PR #280 introduced countdown
    // copy ("Need N more days") so the user knows when the chart
    // will become useful. Mini program inherits the same threshold.
    pmcMessage: t('Not enough data yet for stable load tracking'),
    loadMessage: t('Not enough data yet for weekly load comparison'),

    // Compliance bar legend.
    plannedLabel: t('Planned'),
    actualLabel: t('Actual'),
    zoneMethodology: t(
      'Distribution match uses Bray-Curtis similarity to compare observed and target time-in-zone shares. It appears only when every recent activity has at least 90% duration coverage from valid splits or timestamped samples; sample streams also require a median cadence of 5 seconds or less. These evidence gates are Praxys operational estimates.',
    ),
    complianceMethodology: t(
      'Compliance is the mean weekly actual-to-planned load ratio across completed weeks where actual and planned load both use exact selected-base inputs and the plan target is positive. Estimated weeks stay in the chart but are excluded from the summary. This is an execution comparison, not a quality, safety, recovery, or readiness score.',
    ),

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
  /** `tsb` | `dist` | `load` | `volume` — drives the wx:key. */
  id: string;
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

  /** Active pill — drives which chart renders below the switcher. */
  activePill: DiagnosisPill;
  /** True iff the response contains any zone targets to render the
   *  "Zones" pill against. Hides the pill (and skips it on persist
   *  rehydrate) when there's nothing to show. */
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

  activePill: 'form',
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
 * Build the four stat-strip cells from the server-owned summary.
 * Values stay neutral because TSB and execution ratios are descriptive,
 * not physiological quality, safety, or readiness scores.
 */
function buildStatCells(
  response: TrainingResponse,
  tr: ReturnType<typeof buildTrainingTr>,
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
    label: tr.statTsbLabel,
    value: tsbValue,
    sub: tsbSub,
    unit: '',
  });

  const distMatch = response.summary.distribution_match_pct;
  const theoryName = response.diagnosis?.theory_name;
  cells.push({
    id: 'dist',
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
    label: tr.statLoadLabel,
    value: loadCompliance != null ? `${loadCompliance}` : '—',
    sub: tr.statLoadSub,
    unit: loadCompliance != null ? '%' : '',
  });

  // Volume — weekly average km. Foreground default tone (no verdict).
  const weeklyKm = response.diagnosis?.volume?.weekly_avg_km;
  const lookback = response.diagnosis?.lookback_weeks ?? 0;
  cells.push({
    id: 'volume',
    label: tr.statVolumeLabel,
    value: weeklyKm != null ? weeklyKm.toFixed(1) : '—',
    sub: tFmt('km / week, {0}wk avg', lookback),
    unit: '',
  });

  return cells;
}

function buildState(
  response: TrainingResponse,
  themeClass: string,
  insight: AiInsight | null,
  activePill: DiagnosisPill,
  tr: ReturnType<typeof buildTrainingTr>,
): Partial<TrainingState> {
  const { diagnosis, fitness_fatigue, weekly_review, data_meta } = response;
  const distribution = diagnosis?.distribution ?? [];
  const distributionAvailable = !!diagnosis && diagnosis.data_meta.distribution_complete;
  const hasZones =
    distributionAvailable && distribution.some((z) => z.target_pct != null);
  const dataDays = data_meta?.data_days ?? 0;
  const hasAnyData =
    !!diagnosis?.volume?.weekly_avg_km ||
    (distributionAvailable && distribution.length > 0) ||
    (fitness_fatigue?.dates?.length ?? 0) > 0;

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

  // Active pill: if the persisted choice is `zones` but the response
  // has no targets, fall back to `form`. Same defensive default web
  // applies via the `?` chain on options.
  const resolvedPill: DiagnosisPill =
    activePill === 'zones' && !hasZones ? 'form' : activePill;

  const lookback = diagnosis?.lookback_weeks;
  const diagnosisEyebrow = lookback
    ? tFmt('Last {0} weeks', lookback)
    : tr.diagnosis;

  return {
    themeClass,
    loading: false,
    errorMessage: '',
    hasResponse: true,
    hasAnyData,

    diagnosisEyebrow,
    cells: buildStatCells(response, tr),

    activePill: resolvedPill,
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


    coach,
    coachTr,
    detailsOpen,
    coachToggleLabel: coachToggleLabelText,
    coachDatasetHash,
    coachFeedbackVote,
  };
}

function loadActivePill(): DiagnosisPill {
  try {
    const stored = wx.getStorageSync<string>(DIAGNOSIS_CHART_KEY);
    if (stored === 'form' || stored === 'zones' || stored === 'compliance') {
      return stored;
    }
  } catch {
    // Storage unavailable on first launch is fine — fall through to default.
  }
  return 'form';
}

function persistActivePill(pill: DiagnosisPill): void {
  try {
    wx.setStorageSync(DIAGNOSIS_CHART_KEY, pill);
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[training] could not persist active pill:', e);
  }
}

interface PageMethods extends WechatMiniprogram.IAnyObject {
  onPickPill(e: WechatMiniprogram.TouchEvent): void;
  onToggleCoachDetails(): void;
  onScrollRefresh(): void;
  onRetry(): void;
  refetch(): Promise<void>;
}

Page<TrainingState & { tr: ReturnType<typeof buildTrainingTr> }, PageMethods>({
  data: { ...initialData, tr: buildTrainingTr() },

  onLoad() {
    const tc = themeClassName();
    this.setData({
      themeClass: tc,
      chartTheme: tc === 'theme-light' ? 'light' : 'dark',
      tr: buildTrainingTr(),
      activePill: loadActivePill(),
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
    if (curLocale !== pgMut._locale) {
      pgMut._locale = curLocale;
      this.setData({ tr: buildTrainingTr() });
      void this.refetch();
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

  /**
   * Pill switcher tap. The `data-pill` attribute on the WXML tap
   * surface carries the next chart id. Persist the choice so the user
   * lands on their preferred chart on every visit, matching web's
   * `localStorage.setItem(DIAGNOSIS_CHART_KEY, …)` behavior.
   */
  onPickPill(e: WechatMiniprogram.TouchEvent) {
    const next = e.currentTarget.dataset.pill as DiagnosisPill | undefined;
    if (!next || next === this.data.activePill) return;
    if (next === 'zones' && !this.data.hasZones) return;
    this.setData({ activePill: next });
    persistActivePill(next);
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

  async refetch() {
    const pageState = this as unknown as Record<string, unknown>;
    const previousRequestId = typeof pageState._refetchRequestId === 'number'
      ? pageState._refetchRequestId
      : 0;
    const requestId = previousRequestId + 1;
    pageState._refetchRequestId = requestId;
    this.setData({ loading: true, errorMessage: '' });
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
          this.data.activePill,
          this.data.tr,
        ) as Record<string, unknown>,
      );
    } catch (e) {
      if (pageState._refetchRequestId !== requestId) return;
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
