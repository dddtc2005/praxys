import { setTabBarSelected } from '../../utils/tabbar';
import type { IAppOption } from '../../app';
import { apiGet, apiPost } from '../../utils/api-client';
import { generateShareCard } from '../../utils/share-image';
import type { ApiError } from '../../utils/api-client';
import type {
  PlanData,
  RecoveryAnalysis,
  TodayResponse,
  TrainingSignal,
} from '../../types/api';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { t, tFmt, tNamed, detectLocale } from '../../utils/i18n';
import { coachToggleLabel } from '../../utils/insights';
import { recordProductEventOnce } from '../../utils/product-events';
import { copyUrlToClipboard } from '../../utils/markdown';
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
    unscheduled: { label: 'NO PLAN', subtitle: t('No Workout Scheduled'), color: 'amber' },
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
  tone: 'positive' | 'warning' | 'neutral';
  text: string;
}

interface CoachRecRow {
  /** 1-based ordinal as a string for WXML rendering. Doubles as the
   *  `wx:key` since recommendations are presented in a stable order. */
  index: string;
  text: string;
}

interface CoachReceipt {
  /** Deterministic Today guidance has no generation-time stamp. */
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
 *  PR #238 layout. Five cells when readiness is unavailable (HRV /
 *  observation-count Trend / RHR / Sleep / TSB); six when an Oura-style readiness
 *  score is present, inserting Readiness between Sleep and TSB so
 *  sleep + readiness pair visually. */
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
  /** True when this cell should span both columns (the last cell in
   *  an odd-count layout — currently the 5-cell variant where TSB
   *  would otherwise strand an empty slot). Set during cell assembly,
   *  not at the use site, so WXML doesn't have to know the count. */
  span: boolean;
}

function localizedSignalReason(signal: TrainingSignal): string {
  const rawTsb = signal.reason_args?.tsb ?? signal.recovery.tsb;
  const tsb = rawTsb == null ? '' : Number(rawTsb).toFixed(0);
  const cv = Number(signal.reason_args?.cv ?? 0).toFixed(0);
  const sleep = Number(signal.reason_args?.sleep ?? 0).toFixed(0);

  switch (signal.reason_code) {
    case 'unscheduled_hrv_caution':
      return t('No workout is scheduled, and HRV is below your personal caution band. Keep the day restorative rather than adding a hard session.');
    case 'unscheduled_high_load':
      return tNamed('No workout is scheduled, and modeled load balance is low (TSB {tsb}). Avoid adding intensity today.', { tsb });
    case 'unscheduled_open':
      return t('No workout is scheduled. Add a session only if it fits your broader plan.');
    case 'rest_scheduled':
      return t('Rest day scheduled. Follow the plan and prioritize recovery.');
    case 'hrv_stale':
      return t('The latest HRV reading is out of date. Follow the plan without an HRV-based recovery adjustment.');
    case 'hrv_zero_variance':
      return t('Recent HRV observations have no measurable variation, so Praxys cannot form a reliable recovery band yet. Follow the plan without an HRV-based adjustment.');
    case 'hrv_history_insufficient':
      return t('More historical HRV observations are needed before Praxys can form a personal recovery band. Follow the plan without an HRV-based adjustment.');
    case 'hrv_unavailable':
      return t('Recovery requires current HRV data. Connect or sync an HRV-capable device to receive recovery suggestions.');
    case 'hrv_below_hard':
      return t('HRV is below your personal caution band. Treat this as a recovery signal, not a diagnosis.');
    case 'hrv_below_easy':
      return t('HRV is below your personal caution band. Keep today easy to support recovery.');
    case 'high_load_hard':
      return tNamed('HRV is within your personal reference band, but modeled load balance is low (TSB {tsb}). Modify the hard session.', { tsb });
    case 'hrv_declining_hard':
      return t('HRV rolling mean is lower than its prior window. Reduce intensity as a conservative coaching adjustment.');
    case 'hrv_declining_easy':
      return t('HRV rolling mean is lower than its prior window. Stay easy today.');
    case 'hrv_variability_high':
      return tNamed('HRV variability is high (CV {cv}%), above the selected coaching caution threshold.', { cv });
    case 'sleep_low_hard':
      return tNamed("Sleep score is low ({sleep}). Consider reducing today's intensity.", { sleep });
    case 'resting_hr_elevated_hard':
      return t('Resting heart rate is elevated above your baseline. This can be a caution signal, but it is not diagnostic.');
    case 'hrv_above_baseline':
      return t('HRV is above your personal reference band. Follow the plan as written.');
    case 'recovery_normal':
      return t('Recovery signals are within their recent reference bands. Follow the plan as written.');
    default:
      return signal.reason;
  }
}

function localizedSignalAlternatives(signal: TrainingSignal): string[] {
  if (!signal.alternative_codes?.length) return signal.alternatives;

  return signal.alternative_codes.map((item, index) => {
    const workout = String(item.args.workout ?? signal.plan.workout_type ?? '');
    switch (item.code) {
      case 'restorative_movement':
        return t('Rest, walk, or do gentle mobility');
      case 'optional_easy_short':
        return t('Keep any optional movement easy and short');
      case 'full_recovery_reassess':
        return t('Make today a full recovery day and reassess the hard session tomorrow');
      case 'drop_to_easy':
        return t('Drop to easy run (keep power in recovery zone)');
      case 'push_to_tomorrow_if_easy':
        return tNamed('Push {workout} to tomorrow if tomorrow is rest/easy', { workout });
      case 'cap_low_power':
        return t('Run as planned but cap at low end of power range');
      case 'swap_for_easy':
        return tNamed('Swap {workout} for easy run', { workout });
      case 'drop_one_zone':
        return t('Drop intensity by one zone');
      case 'push_to_tomorrow':
        return tNamed('Push {workout} to tomorrow', { workout });
      case 'proceed_monitor_body':
        return t('Run as planned but monitor how you feel');
      case 'shorten_if_fatigued':
        return t('Shorten the session if fatigue develops');
      case 'run_easy':
        return t('Run easy instead');
      case 'monitor_hr_drift':
        return t('Proceed but monitor heart-rate drift during the session');
      default:
        return signal.alternatives[index] ?? '';
    }
  }).filter(Boolean);
}

/** Build the deterministic Coach receipt from the canonical Today signal. */
function buildCoachReceipt(
  response: TodayResponse,
  recoveryName: string | undefined,
  loadName: string | undefined,
): CoachReceipt {
  const recommendations: CoachRecRow[] = localizedSignalAlternatives(response.signal).map(
    (text, index) => ({ index: `${index + 1}`, text }),
  );
  const attribution = [recoveryName, loadName].filter((s): s is string => !!s).join(' · ');
  return {
    stamp: '',
    headline: localizedSignalReason(response.signal),
    hasFindings: false,
    findings: [],
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

const HRV_TREND_LABEL: Record<'stable' | 'improving' | 'declining', string> = {
  stable: 'stable',
  improving: 'rising',
  declining: 'falling',
};

const RHR_TREND_LABEL: Record<'stable' | 'elevated' | 'low', string> = {
  stable: 'near baseline',
  elevated: 'above baseline',
  low: 'below baseline',
};

// ESTIMATE: Praxys display labels for modeled training stress balance (TSB).
// Banister motivates the load model, but does not validate these product bands.
//   ≥ +10  positive balance
//   0..10  slightly positive
//   -10..0 slightly negative
//   < -10  negative balance
const TSB_STRONGLY_POSITIVE = 10;
const TSB_MILD_FATIGUE = -10;

function tsbDescriptor(tsb: number | null): string {
  if (tsb == null) return t('not enough load history');
  if (tsb >= TSB_STRONGLY_POSITIVE) return t('positive balance');
  if (tsb > 0) return t('slightly positive');
  if (tsb > TSB_MILD_FATIGUE) return t('slightly negative');
  return t('negative balance');
}

/** Build the supporting metrics row that replaces the prior Form/TSB
 *  sparkline + Recovery card. Order mirrors web's PR #238: HRV,
 *  observation-count Trend, RHR, Sleep, [Readiness when present], TSB. The last
 *  cell is marked `span` only when the total count is odd, so the
 *  2-col grid never strands an empty slot. */
function buildSupportingCells(
  ra: RecoveryAnalysis | null,
  tsb: number | null,
  observationCount: number,
  locale: 'en' | 'zh',
): SupportingCell[] {
  const noData = t('no data');
  const hrv = ra?.hrv ?? null;
  const provenance = (metricDate: string | null | undefined): string | null => (
    metricDate ? tFmt('from {0}', formatIsoDateShort(metricDate, locale)) : null
  );

  // Cell 1 — HRV (latest ln RMSSD observation).
  const hrvValue = hrv ? hrv.today_ln.toFixed(2) : '—';
  const hrvSub = hrv
    ? [
        hrv.today_ms != null ? `${hrv.today_ms} ms` : null,
        tFmt('vs {0} baseline', hrv.baseline_mean_ln.toFixed(2)),
        provenance(ra?.hrv_latest_date),
      ].filter(Boolean).join(' · ')
    : noData;

  // Cell 2 — observation-count Trend (arrow + neutral direction + rolling CV%).
  const trendValue = hrv ? TREND_ARROW[hrv.trend] : '—';
  const trendSub = hrv
    ? `${t(HRV_TREND_LABEL[hrv.trend])} · CV ${hrv.rolling_cv.toFixed(1)}%`
    : noData;

  // Cell 3 — Resting HR. Show a baseline comparison only when available.
  const rhrValue = ra?.resting_hr != null ? `${Math.round(ra.resting_hr)}` : '—';
  let rhrSub: string;
  if (ra?.resting_hr == null) {
    rhrSub = noData;
  } else {
    rhrSub = [
      'bpm',
      ra.rhr_trend ? t(RHR_TREND_LABEL[ra.rhr_trend]) : null,
      provenance(ra.rhr_latest_date),
    ].filter(Boolean).join(' · ');
  }

  // Cell 4 — Sleep score (Oura/Garmin daily sleep score, 0–100).
  const sleepValue = ra?.sleep_score != null ? `${Math.round(ra.sleep_score)}` : '—';
  const sleepSub = ra?.sleep_score != null
    ? [t('overnight score'), provenance(ra.sleep_latest_date)].filter(Boolean).join(' · ')
    : noData;

  // Cell 5 (Oura only) — Readiness score (0–100). Distinct from
  // sleep_score; rendered side-by-side when the source provides both.
  const hasReadiness = ra?.readiness_score != null;
  const readinessValue = hasReadiness && ra ? `${Math.round(ra.readiness_score!)}` : '—';
  const readinessSub = [
    t('daily score'),
    provenance(ra?.readiness_latest_date),
  ].filter(Boolean).join(' · ');

  // TSB (signed, 1dp). Tint green when freshness is positive.
  const tsbValue = tsb == null ? '—' : `${tsb >= 0 ? '+' : ''}${tsb.toFixed(1)}`;
  const tsbAccent = tsb != null && tsb > 0 ? 'today-cell-value-positive' : '';

  const cells: SupportingCell[] = [
    { id: 'hrv', label: t('HRV (ln RMSSD)'), value: hrvValue, sub: hrvSub, valueAccent: '', span: false },
    { id: 'trend', label: tNamed('{observationCount}-observation Trend', { observationCount }), value: trendValue, sub: trendSub, valueAccent: '', span: false },
    { id: 'rhr', label: t('RHR'), value: rhrValue, sub: rhrSub, valueAccent: '', span: false },
    { id: 'sleep', label: t('Sleep'), value: sleepValue, sub: sleepSub, valueAccent: '', span: false },
  ];
  if (hasReadiness) {
    cells.push({ id: 'readiness', label: t('Readiness'), value: readinessValue, sub: readinessSub, valueAccent: '', span: false });
  }
  cells.push({ id: 'tsb', label: t('TSB'), value: tsbValue, sub: tsbDescriptor(tsb), valueAccent: tsbAccent, span: false });

  // Span the last cell only when the total count is odd — that's the
  // 5-cell variant (no readiness). With 6 cells the grid is balanced
  // and TSB sits in column 2 of the third row.
  if (cells.length % 2 === 1) {
    cells[cells.length - 1].span = true;
  }
  return cells;
}

/** Format the planned-workout one-liner. Returns the unscheduled fallback
 *  when no workout is scheduled. Mirrors web/src/pages/Today.tsx. */
function formatPlan(plan: PlanData | null | undefined): string {
  if (!plan?.workout_type) return t('No workout scheduled.');
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
  /** Localized long-form date for the page eyebrow. Sourced from the
   *  server's `as_of_date` once a response arrives — falls back to the
   *  device's local date for the loading skeleton (so the skeleton
   *  renders something reasonable rather than blank). */
  today: string;
  asOfDate: string;
  /** Recovery-only staleness advisory (PR #254 surface) — fires only
   *  when recovery rows are ≥2 days behind. Empty string hides the
   *  banner. Suppressed when `dataStale` is also true so the
   *  page-level banner below is the single voice on the surface. */
  stalenessText: string;
  /** Page-level data-staleness state. Anchored on source measurements,
   *  with the server's one-day grace for overnight recovery data. */
  dataStale: boolean;
  /** Pre-formatted "Sat 9:00 PM" / "周六 21:00" stamp for the banner. */
  dataAsOfLabel: string;
  /** Pre-translated headline for the banner — already carries the
   *  formatted timestamp. */
  staleHeadline: string;
  /** Pre-translated detail line. */
  staleDetail: string;
  /** Pre-translated chip text — "From {label}". */
  staleChipText: string;
  /** Pre-translated button labels — split out so WXML stays stringless
   *  and the i18n-check linter doesn't flag the template. */
  staleSyncLabel: string;
  staleSyncingLabel: string;
  staleShowAnywayLabel: string;
  /** "Show anyway" escape-hatch state — component-scoped (not
   *  storage). Each fresh page load re-prompts. */
  staleDismissed: boolean;
  /** Manual-sync in-flight. Toggles button text and disables. */
  staleSyncing: boolean;
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;

  signalLabel: string;
  signalSubtitle: string;
  signalColor: 'green' | 'amber' | 'red';
  /** Canonical reason text. It is hidden when the same deterministic
   *  sentence is rendered in the Coach receipt below. */
  signalReason: string;
  signalAlternatives: CoachRecRow[];
  hasCoach: boolean;
  coach: CoachReceipt | null;
  coachTr: CoachTranslations | null;
  /** Findings + recommendations are progressively disclosed; default
   *  collapsed so the receipt reads as headline-first. Mirrors web's
   *  AiInsightsCard. */
  detailsOpen: boolean;
  /** Pre-computed toggle button label — `{N} findings · {M} recs` when
   *  collapsed, "Hide details" when expanded. Empty string hides the
   *  toggle entirely (zero findings + zero recs). */
  coachToggleLabel: string;
  decisionCheckEligible: boolean;

  /** Five or six supporting metrics: HRV, trend, RHR, sleep, optional
   *  readiness, and TSB. Missing values render as `—`. */
  cells: SupportingCell[];

  planEyebrow: string;
  planText: string;

  methodologyExpanded: boolean;
  methodologyLabel: string;
  methodologyText: string;
  methodologySourceActionLabel: string;
  methodologySources: Array<{ id: string; label: string; url: string }>;

  hasWarnings: boolean;
  warnings: string[];
}

// Format an ISO `YYYY-MM-DD` as a long-form localized date, parsing as a
// local calendar date (not UTC midnight) so server-emitted "2026-05-02"
// doesn't shift backward in negative-offset timezones. Falls back to the
// raw string on parse failure so the eyebrow is never blank.
function formatIsoDateLong(isoDate: string, locale: 'en' | 'zh'): string {
  const [y, m, day] = isoDate.split('-').map(Number);
  if (!y || !m || !day) return isoDate;
  return new Date(y, m - 1, day).toLocaleDateString(
    locale === 'zh' ? 'zh-CN' : 'en-US',
    { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' },
  );
}

// Short ("Apr 24" / "4月24日") variant used inside the staleness banner
// so the latest-reading-date chip reads compactly inline.
function formatIsoDateShort(isoDate: string, locale: 'en' | 'zh'): string {
  const [y, m, day] = isoDate.split('-').map(Number);
  if (!y || !m || !day) return isoDate;
  return new Date(y, m - 1, day).toLocaleDateString(
    locale === 'zh' ? 'zh-CN' : 'en-US',
    { month: 'short', day: 'numeric' },
  );
}

// Build the staleness advisory string, or '' to hide the banner.
// Mirrors web/src/pages/Today.tsx — same conditions, same wording so a
// user moving between surfaces gets a consistent message. Note we
// deliberately don't flag client-vs-server-date divergence as a
// "timezone changed" signal: the server runs in a single fixed tz
// (UTC on Azure), so a 1-day offset is the steady state for half the
// world. The eyebrow renders `as_of_date` honestly, which is enough.
function buildStalenessText(
  ra: RecoveryAnalysis | null,
  locale: 'en' | 'zh',
): string {
  const recoveryStale = ra?.is_stale === true && !!ra?.latest_date;
  if (!recoveryStale || !ra?.latest_date) return '';
  return tFmt(
    "Recovery data hasn't synced yet. Showing the latest reading from {0}.",
    formatIsoDateShort(ra.latest_date, locale),
  );
}

// Format the `data_as_of` server timestamp for the banner — local-TZ
// weekday + clock time ("Sat 9:00 PM" / "周六 21:00"). The server emits
// the value with a trailing `Z` so `new Date()` interprets it as UTC
// and renders in the user's local timezone, which is what we want them
// to read. Returns '' on parse failure so the WXML guard hides the
// banner cleanly rather than rendering "Invalid Date".
function formatDataAsOf(iso: string, locale: 'en' | 'zh'): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
      weekday: 'short',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[today] formatDataAsOf failed; hiding banner:', iso, e);
    return '';
  }
}

// A prior-date snapshot is stale unless it carries a recovery reading the
// server still considers current. Overnight sleep/HRV is commonly stored
// under yesterday's date, so the backend's one-day grace must also keep the
// Today decision check active on the mini program.
function isDataStaleNow(
  dataAsOf: string | null | undefined,
  recovery: RecoveryAnalysis | null | undefined,
): boolean {
  if (!dataAsOf) return false;
  const d = new Date(dataAsOf);
  if (Number.isNaN(d.getTime())) return false;
  const dataLocal = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const now = new Date();
  const todayLocal = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  if (dataLocal >= todayLocal) return false;
  return !recovery?.latest_date || recovery.is_stale;
}

function isCurrentLocalDay(timestamp: number): boolean {
  const value = new Date(timestamp);
  const now = new Date();
  return (
    value.getFullYear() === now.getFullYear()
    && value.getMonth() === now.getMonth()
    && value.getDate() === now.getDate()
  );
}

function isDecisionCheckEligibleNow(response: TodayResponse): boolean {
  const hasDecisionContext = (
    response.data_as_of != null || Boolean(response.signal.plan?.workout_type)
  );
  return (
    hasDecisionContext
    && !isDataStaleNow(response.data_as_of, response.recovery_analysis)
    && !buildStalenessText(response.recovery_analysis ?? null, detectLocale())
  );
}

function buildRenderState(
  response: TodayResponse | null,
  themeClass: string,
  today: string,
  staleDismissed = false,
  staleSyncing = false,
): Partial<RenderState> {
  if (!response) {
    return {};
  }

  const meta = signalMeta()[response.signal.recommendation] ?? signalMeta().follow_plan;

  // Eyebrow date now comes from the server's `as_of_date` (parsed as
  // local-calendar) rather than `new Date()` — see buildStalenessText
  // for the reasoning. The fall-back local date the page set on first
  // load is replaced once the response arrives.
  const localeForDate = detectLocale();
  const eyebrowDate = formatIsoDateLong(response.as_of_date, localeForDate);

  // Page-level staleness uses source measurements and honors the backend's
  // one-day grace for yesterday-dated overnight recovery data.
  const dataStale = isDataStaleNow(response.data_as_of, response.recovery_analysis);
  const dataAsOfLabel = response.data_as_of
    ? formatDataAsOf(response.data_as_of, localeForDate)
    : '';
  const dataStaleEffective = dataStale && !!dataAsOfLabel;

  const stalenessText = dataStaleEffective
    ? ''
    : buildStalenessText(response.recovery_analysis ?? null, localeForDate);

  const staleHeadline = dataStaleEffective
    ? tFmt(
        "Showing yesterday's snapshot. Last reading {0}.",
        dataAsOfLabel,
      )
    : '';
  const staleDetail = dataStaleEffective
    ? t('No new HRV, sleep, or activity since.')
    : '';
  const staleChipText = dataStaleEffective
    ? tFmt('From {0}', dataAsOfLabel)
    : '';

  // Today has one same-day narrative source: the deterministic signal.
  // Render it in the established Coach receipt without fetching or accepting
  // a persisted daily insight row.
  const recoveryNoteName = response.science_notes?.recovery?.name;
  const loadNoteName = response.science_notes?.load?.name;
  const coach = buildCoachReceipt(response, recoveryNoteName, loadNoteName);
  const hasCoach = Boolean(coach.headline);
  const coachTr: CoachTranslations | null = hasCoach
    ? {
        mark: t('Praxys Coach'),
        findings: t('Findings'),
        recommendations: t('Recommendations'),
        aria: t('Praxys Coach guidance'),
      }
    : null;
  // Reset detailsOpen on every refetch. The deterministic receipt content may
  // changed (different findings / recs), so showing the prior
  // expanded state would surface a stale-looking detail block.
  const detailsOpen = false;
  const coachLabel = coach
    ? coachToggleLabel(
        coach.findings.length,
        coach.recommendations.length,
        detailsOpen,
      )
    : '';

  const cells = buildSupportingCells(
    response.recovery_analysis ?? null,
    response.signal.recovery.tsb,
    response.recovery_theory?.params.rolling_days ?? 7,
    localeForDate,
  );

  const warnings = response.warnings ?? [];
  const methodologySources = [
    response.science_notes?.recovery?.citations?.[0],
    response.science_notes?.load?.citations?.[0],
  ].filter((citation): citation is { label: string; url: string } => Boolean(citation?.url))
    .map((citation, index) => ({
      id: `${index}-${citation.url}`,
      label: citation.label,
      url: citation.url,
    }));

  return {
    themeClass,
    today: eyebrowDate,
    asOfDate: response.as_of_date,
    stalenessText,
    dataStale: dataStaleEffective,
    dataAsOfLabel,
    staleHeadline,
    staleDetail,
    staleChipText,
    staleSyncLabel: t('Sync now'),
    staleSyncingLabel: t('Syncing…'),
    staleShowAnywayLabel: t('Show anyway'),
    staleDismissed,
    staleSyncing,
    loading: false,
    errorMessage: '',
    hasResponse: true,

    signalLabel: meta.label,
    signalSubtitle: meta.subtitle,
    signalColor: meta.color,
    signalReason: hasCoach ? '' : response.signal.reason,
    signalAlternatives: hasCoach
      ? []
      : (response.signal.alternatives || []).map((text, index) => ({
          index: `${index + 1}`,
          text,
        })),
    hasCoach,
    coach,
    coachTr,
    detailsOpen,
    coachToggleLabel: coachLabel,
    decisionCheckEligible: isDecisionCheckEligibleNow(response),

    cells,

    planEyebrow: t('Planned · Today'),
    planText: formatPlan(response.signal.plan),

    methodologyExpanded: false,
    methodologyLabel: t('How this is calculated'),
    methodologyText: t("Today's recommendation combines the scheduled workout with Praxys operational adaptations of your active recovery and load models. HRV requires a current reading, while TSB is modeled load balance rather than a direct measure of fatigue. Praxys TSB display labels and the one-CTL-window history gate are operational estimates, not validated cutoffs. These coaching guardrails are not a medical diagnosis."),
    methodologySourceActionLabel: t('Copy source URL'),
    methodologySources,

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
  asOfDate: '',
  stalenessText: '',
  dataStale: false,
  dataAsOfLabel: '',
  staleHeadline: '',
  staleDetail: '',
  staleChipText: '',
  staleSyncLabel: '',
  staleSyncingLabel: '',
  staleShowAnywayLabel: '',
  staleDismissed: false,
  staleSyncing: false,
  loading: true,
  errorMessage: '',
  hasResponse: false,
  refreshing: false,

  signalLabel: '',
  signalSubtitle: '',
  signalColor: 'green',
  signalReason: '',
  signalAlternatives: [],
  hasCoach: false,
  coach: null,
  coachTr: null,
  detailsOpen: false,
  coachToggleLabel: '',
  decisionCheckEligible: false,

  cells: [],

  planEyebrow: '',
  planText: '',

  methodologyExpanded: false,
  methodologyLabel: '',
  methodologyText: '',
  methodologySourceActionLabel: '',
  methodologySources: [],

  hasWarnings: false,
  warnings: [],

  shareImagePath: '',
  shareCardVisible: false,
  shareCardTheme: '',
};

// Translation table — built per page-load (Locale changes reLaunch).
const initialTr = buildTranslations();
let todayPageVisible = false;

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
    const pageState = this as unknown as Record<string, unknown>;
    pageState._locale = getApp<IAppOption>().globalData.locale;
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
    todayPageVisible = true;
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
    const returningToTab = pgMut._hasShownOnce === true;
    pgMut._hasShownOnce = true;
    let localeChanged = false;
    if (curLocale !== pgMut._locale) {
      pgMut._locale = curLocale;
      localeChanged = true;
      this.setData({ tr: buildTranslations() });
    }
    if (returningToTab || localeChanged) {
      void this.refetch({ background: true });
    }
    const cachedResponse = pgMut._todayResponse as TodayResponse | undefined;
    const fetchedAt = typeof pgMut._todayResponseFetchedAt === 'number'
      ? pgMut._todayResponseFetchedAt
      : 0;
    const baseEligible = cachedResponse && isCurrentLocalDay(fetchedAt)
      ? isDecisionCheckEligibleNow(cachedResponse)
      : false;
    pgMut._decisionCheckBaseEligible = baseEligible;
    if (this.data.decisionCheckEligible !== baseEligible) {
      this.setData({ decisionCheckEligible: baseEligible });
    }
    if (cachedResponse) {
      recordProductEventOnce('today_brief_rendered', cachedResponse.as_of_date);
    }
    applyThemeChrome();
    setTabBarSelected(this, 0);
  },

  onHide() {
    todayPageVisible = false;
    this.setData({ decisionCheckEligible: false });
  },

  onUnload() {
    todayPageVisible = false;
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

  /**
   * Tap-toggle the Coach Receipt's findings + recommendations. Only
   * surfaces when there's something to disclose; the WXML guards on
   * `coachToggleLabel`. Recompute the label so "{N} findings · {M}
   * recs" flips to "Hide details" without a re-render of the rest
   * of the receipt body.
   */
  onToggleCoachDetails() {
    const next = !this.data.detailsOpen;
    if (next && this.data.asOfDate) {
      recordProductEventOnce('today_reasoning_opened', this.data.asOfDate);
    }
    const coach = this.data.coach;
    if (!coach) return;
    const label = coachToggleLabel(
      coach.findings.length,
      coach.recommendations.length,
      next,
    );
    this.setData({ detailsOpen: next, coachToggleLabel: label });
  },

  /** "Show anyway" handler — dismisses the staleness banner for the
   *  current page session. Re-renders from cached `_todayResponse` so
   *  the chip variant takes its place without a network round-trip. */
  onStaleShowAnyway() {
    this.setData({ staleDismissed: true });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const cached = (this as unknown as Record<string, any>)._todayResponse;
    if (cached) {
      this.setData(
        buildRenderState(
          cached,
          this.data.themeClass,
          this.data.today,
          true,
          this.data.staleSyncing as boolean,
        ) as Record<string, unknown>,
      );
    }
  },

  /** "Sync now" handler — kicks the existing /api/sync route and
   *  polls /api/sync/status until no source reports ``syncing``.
   *  data_as_of advances only if the sync pulled new rows; on a no-op
   *  sync, the banner correctly stays up. The five-minute deadline covers
   *  first-time backfill plus the two durable insight-generation calls;
   *  a bare 6s sleep would re-arm the button before sync
   *  could plausibly finish. Errors swallow at this layer because the
   *  failure mode the user cares about — "did the data refresh?" —
   *  is observable from the banner staying or going away. */
  async onStaleSyncNow() {
    if (this.data.staleSyncing) return;
    this.setData({ staleSyncing: true });
    try {
      try {
        await apiPost('/api/sync');
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[today] manual sync kick failed; refetching anyway:', e);
      }
      const deadline = Date.now() + 300_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 2_000));
        try {
          const status = await apiGet<Record<string, { status?: string }>>(
            '/api/sync/status',
          );
          const stillSyncing = Object.values(status).some(
            (s) => s?.status === 'syncing',
          );
          if (!stillSyncing) break;
        } catch {
          // Transient network blip — keep polling. Deadline guards
          // against an indefinitely-broken status endpoint.
        }
      }
      await this.refetch();
    } finally {
      this.setData({ staleSyncing: false });
    }
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
    // The receipt and share card use the same deterministic signal reason.
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


  toggleMethodology() {
    this.setData({ methodologyExpanded: !this.data.methodologyExpanded });
  },

  onTapMethodologySource(event: WechatMiniprogram.TouchEvent) {
    const url = String(event.currentTarget.dataset.url ?? '');
    if (url) copyUrlToClipboard(url);
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
      // Today guidance is deterministic. Fetch only the canonical signal;
      // generated daily prose is intentionally not requested.
      const response = await apiGet<TodayResponse>('/api/today');
      if (pageState._refetchRequestId !== requestId) return;
      // Cache raw response so renderShareCard / onStaleShowAnyway can
      // access it without a second network round-trip.
      pageState._todayResponse = response;
      pageState._todayResponseFetchedAt = Date.now();
      const renderState = buildRenderState(
        response,
        this.data.themeClass,
        this.data.today,
        this.data.staleDismissed as boolean,
        this.data.staleSyncing as boolean,
      );
      pageState._decisionCheckBaseEligible = renderState.decisionCheckEligible;
      renderState.decisionCheckEligible = (
        todayPageVisible && renderState.decisionCheckEligible
      );
      this.setData(renderState as unknown as Record<string, unknown>);
      if (todayPageVisible) {
        recordProductEventOnce('today_brief_rendered', response.as_of_date);
      }

      // Share card is rendered lazily on first FAB tap. Clear any stale
      // path so the old signal's card doesn't show for the new signal.
      this.setData({ shareImagePath: '', shareCardVisible: false });
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
        console.warn('[today] background refresh failed; keeping cached Today response:', detail);
        return;
      }
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },
});
