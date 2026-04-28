import { apiGet } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import type { GoalResponse, Milestone } from '../../types/api';
import { formatTime, formatPace } from '../../utils/format';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import {
  buildShareMessage,
  buildTimelineMessage,
  detectShareLocale,
  getShareMessage,
} from '../../utils/share';
import { copyUrlToClipboard } from '../../utils/markdown';

// Default science-note copy + sources, mirroring web/src/pages/Goal.tsx.
// Used as fallback when the backend doesn't provide a science_notes.prediction
// override. URLs are stable (Stryd / runningwritings.com).
const SCIENCE_POWER_URL = 'https://help.stryd.com/en/articles/6879547-race-power-calculator';
const SCIENCE_PACE_URL =
  'https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html';
const SCIENCE_ULTRA_URL =
  'https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html';
const ULTRA_DISTANCES = new Set(['50k', '50mi', '100k', '100mi']);

const DEFAULT_POWER_NOTE =
  'Predicted using Stryd race power model (5K at 103.8% CP, marathon at 89.9% CP).';
const DEFAULT_PACE_NOTE =
  "Predicted using Riegel's formula (T₂ = T₁ × (D₂/D₁)^1.06), treating threshold pace as ~10K effort.";
const ULTRA_NOTE =
  "Ultra distance power fractions (50K+) are estimates with limited research backing. " +
  "Riegel's exponent is validated only up to marathon distance. Predictions beyond marathon " +
  'carry significantly higher uncertainty due to factors like fueling, terrain, heat, and pacing ' +
  'strategy that dominate ultra performance but are not captured by power/pace models.';

interface PredictionNote {
  text: string;
  url: string;
}

function predictionNote(response: GoalResponse): PredictionNote {
  const pred = response.science_notes?.prediction;
  if (pred?.description) {
    const url = pred.citations?.[0]?.url;
    return {
      text: pred.description,
      url: url || (response.training_base === 'power' ? SCIENCE_POWER_URL : SCIENCE_PACE_URL),
    };
  }
  if (response.training_base === 'power') {
    return { text: DEFAULT_POWER_NOTE, url: SCIENCE_POWER_URL };
  }
  return { text: DEFAULT_PACE_NOTE, url: SCIENCE_PACE_URL };
}

function isUltraDistance(distance?: string): boolean {
  return !!distance && ULTRA_DISTANCES.has(distance);
}

/**
 * Mirrors web/src/pages/Goal.tsx — three modes of goal tracking that
 * render very different layouts:
 *
 *   race_date    — race countdown hero + reality check + CP trend
 *   cp_milestone — target CP progress hero + milestone checklist + CP trend
 *   continuous   — current threshold + trend direction + CP trend
 *   none         — empty state ("set a goal on web")
 *
 * Backend `mode` drives the dispatch. All formatting respects
 * `display.threshold_unit` so HR-base and pace-base users get sensible
 * units (bpm / min/km) rather than power's W default.
 */

interface SeriesPayload {
  label: string;
  color: string;
  values: (number | null)[];
  fill?: boolean;
}

interface MilestoneRow {
  cp: number;
  cpDisplay: string;
  marathon: string;
  reached: boolean;
  isCurrent: boolean;
  iconClass: string;
  rowClass: string;
}

interface GoalState {
  themeClass: string;
  chartTheme: 'light' | 'dark';
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;
  mode: GoalResponse['race_countdown']['mode'];

  // Common (CP trend chart shared by all modes that have data).
  hasCpTrend: boolean;
  cpTrendDates: string[];
  cpTrendSeries: SeriesPayload[];
  cpTrendReferenceY: number | null;

  refreshing: boolean;

  // ScienceNote-equivalent: an expandable "How this is calculated"
  // section that shows prediction methodology + tappable source link.
  // Driven by GoalResponse.science_notes.prediction with sensible
  // defaults per training_base. Also a separate ultra-distance caveat
  // when rc.distance is in ULTRA_DISTANCES.
  notePredictionText: string;
  notePredictionUrl: string;
  notePredictionExpanded: boolean;
  hasUltraNote: boolean;
  noteUltraText: string;
  noteUltraUrl: string;
  noteUltraExpanded: boolean;

  // --- race_date mode ---
  rdDistLabel: string;
  rdHasDays: boolean;
  rdDaysLeft: string;
  rdRaceDate: string;
  rdStatusText: string;
  rdStatusAccent: string;
  rdHasPredicted: boolean;
  rdPredictedTime: string;
  rdHasTarget: boolean;
  rdTargetTime: string;
  rdShowReality: boolean;
  rdAssessment: string;
  rdAssessmentAccent: string;
  rdHasGapRow: boolean;
  rdCurrentCp: string;
  rdNeededCp: string;
  rdAbbrev: string;
  rdHasGapValue: boolean;
  rdGapValue: string;
  rdHasTrendNote: boolean;
  rdTrendNote: string;
  rdHasRealistic: boolean;
  rdComfortable: string;
  rdStretch: string;
  rdShowTrendOnly: boolean; // no target → simpler trend card

  // --- cp_milestone mode ---
  cmDistLabel: string;
  cmHero: string; // headline like "Building toward 3:30:00 Marathon"
  cmHasPredicted: boolean;
  cmPredictedTime: string;
  cmHasTarget: boolean;
  cmTargetTime: string;
  cmHasCpProgress: boolean;
  cmCurrentCp: string;
  cmTargetCp: string;
  cmThresholdUnit: string;
  cmProgressPctLabel: string;
  cmProgressBarPct: number;
  cmStatusText: string;
  cmStatusAccent: string;
  cmHasMilestones: boolean;
  cmMilestones: MilestoneRow[];
  cmHasAssessment: boolean;
  cmAssessment: string;
  cmAssessmentAccent: string;
  cmHasEstimatedMonths: boolean;
  cmEstimatedMonths: string;
  cmHasTrendNote: boolean;
  cmTrendNote: string;

  // --- continuous mode ---
  ctCurrentCp: string;
  ctHasCurrentCp: boolean;
  ctThresholdUnit: string;
  ctHasTrend: boolean;
  ctTrendDirection: string;
  ctTrendAccent: string;
  ctHasSlope: boolean;
  ctSlopeText: string;
  ctHasPredicted: boolean;
  ctPredictedTime: string;
  ctDistLabel: string;
  ctHasAssessment: boolean;
  ctAssessment: string;
  ctAssessmentAccent: string;
  ctHasTrendNote: boolean;
  ctTrendNote: string;
}

const initialData: GoalState = {
  themeClass: 'theme-light',
  chartTheme: 'light',
  loading: true,
  errorMessage: '',
  hasResponse: false,
  mode: 'none',

  hasCpTrend: false,
  cpTrendDates: [],
  cpTrendSeries: [],
  cpTrendReferenceY: null,

  refreshing: false,

  notePredictionText: '',
  notePredictionUrl: '',
  notePredictionExpanded: false,
  hasUltraNote: false,
  noteUltraText: ULTRA_NOTE,
  noteUltraUrl: SCIENCE_ULTRA_URL,
  noteUltraExpanded: false,

  rdDistLabel: 'Race',
  rdHasDays: false,
  rdDaysLeft: '',
  rdRaceDate: '',
  rdStatusText: '',
  rdStatusAccent: '',
  rdHasPredicted: false,
  rdPredictedTime: '',
  rdHasTarget: false,
  rdTargetTime: '',
  rdShowReality: false,
  rdAssessment: '',
  rdAssessmentAccent: '',
  rdHasGapRow: false,
  rdCurrentCp: '',
  rdNeededCp: '',
  rdAbbrev: 'CP',
  rdHasGapValue: false,
  rdGapValue: '',
  rdHasTrendNote: false,
  rdTrendNote: '',
  rdHasRealistic: false,
  rdComfortable: '',
  rdStretch: '',
  rdShowTrendOnly: false,

  cmDistLabel: 'Race',
  cmHero: '',
  cmHasPredicted: false,
  cmPredictedTime: '',
  cmHasTarget: false,
  cmTargetTime: '',
  cmHasCpProgress: false,
  cmCurrentCp: '',
  cmTargetCp: '',
  cmThresholdUnit: '',
  cmProgressPctLabel: '',
  cmProgressBarPct: 0,
  cmStatusText: '',
  cmStatusAccent: '',
  cmHasMilestones: false,
  cmMilestones: [],
  cmHasAssessment: false,
  cmAssessment: '',
  cmAssessmentAccent: '',
  cmHasEstimatedMonths: false,
  cmEstimatedMonths: '',
  cmHasTrendNote: false,
  cmTrendNote: '',

  ctCurrentCp: '',
  ctHasCurrentCp: false,
  ctThresholdUnit: 'W',
  ctHasTrend: false,
  ctTrendDirection: 'Flat',
  ctTrendAccent: '',
  ctHasSlope: false,
  ctSlopeText: '',
  ctHasPredicted: false,
  ctPredictedTime: '',
  ctDistLabel: 'Marathon',
  ctHasAssessment: false,
  ctAssessment: '',
  ctAssessmentAccent: '',
  ctHasTrendNote: false,
  ctTrendNote: '',
};

function severityAccent(severity: string): string {
  switch (severity) {
    case 'on_track':
      return 'ts-primary';
    case 'close':
      return 'ts-warning';
    case 'behind':
    case 'unlikely':
      return 'ts-destructive';
    default:
      return 'ts-muted';
  }
}

function trendDirectionLabel(direction: string): string {
  if (direction === 'rising') return 'Rising';
  if (direction === 'falling') return 'Falling';
  return 'Flat';
}

function formatThreshold(value: number, unit: string): string {
  if (unit === '/km') return formatPace(value);
  return `${Math.round(value)}`;
}

function statusBadgeText(status: string): string {
  return status.replace(/_/g, ' ').toUpperCase();
}

function buildState(response: GoalResponse, themeClass: string): Partial<GoalState> {
  const rc = response.race_countdown;
  const display = response.display;
  const unit = display?.threshold_unit ?? 'W';
  const abbrev = display?.threshold_abbrev ?? 'CP';
  const isPace = unit === '/km';
  const trend = response.cp_trend;
  const hasCpTrend = !!trend && trend.values.length >= 2;

  const note = predictionNote(response);
  const ultra = isUltraDistance(rc.distance);

  const result: Partial<GoalState> = {
    themeClass,
    loading: false,
    errorMessage: '',
    hasResponse: true,
    mode: rc.mode,

    hasCpTrend,
    cpTrendDates: hasCpTrend ? trend.dates : [],
    cpTrendSeries: hasCpTrend
      ? [{ label: abbrev, color: '#00ff87', values: trend.values, fill: true }]
      : [],
    // Target reference line shown when the active mode tracks toward
    // a specific CP target — race_date AND cp_milestone both expose
    // rc.target_cp; continuous mode does not (target_cp is null).
    cpTrendReferenceY: rc.target_cp ?? null,

    notePredictionText: note.text,
    notePredictionUrl: note.url,
    // Don't reset expand state on refetch — UX courtesy so a refresh
    // doesn't collapse a note the user opened. This is initialized to
    // false in initialData and toggled by the user only.
    hasUltraNote: ultra,
  };

  if (rc.mode === 'race_date') {
    return { ...result, ...buildRaceDateState(response, unit, abbrev, isPace) };
  }
  if (rc.mode === 'cp_milestone') {
    return { ...result, ...buildCpMilestoneState(response, unit, isPace) };
  }
  if (rc.mode === 'continuous' || rc.mode === 'none') {
    return { ...result, ...buildContinuousState(response, unit, isPace) };
  }
  return result;
}

function buildRaceDateState(
  response: GoalResponse,
  unit: string,
  abbrev: string,
  isPace: boolean,
): Partial<GoalState> {
  const rc = response.race_countdown;
  const rCheck = rc.reality_check;
  const hasTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const distLabel = rc.distance_label ?? 'Race';
  const severityClass = severityAccent(rCheck.severity);
  const showReality = hasTarget && rCheck.severity !== 'unknown';

  return {
    rdDistLabel: distLabel,
    rdHasDays: rc.days_left != null,
    rdDaysLeft: rc.days_left != null ? `${rc.days_left}` : '—',
    rdRaceDate: rc.race_date ?? 'race day',
    rdStatusText: statusBadgeText(rc.status),
    rdStatusAccent: severityClass,
    rdHasPredicted: rc.predicted_time_sec != null,
    rdPredictedTime: rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—',
    rdHasTarget: hasTarget,
    rdTargetTime: hasTarget ? formatTime(rc.target_time_sec as number) : '',
    rdAbbrev: abbrev,

    rdShowReality: showReality,
    rdAssessment: rCheck.assessment ?? '',
    rdAssessmentAccent: severityClass,
    rdHasGapRow: rCheck.current_cp != null && rCheck.needed_cp != null,
    rdCurrentCp:
      rCheck.current_cp != null ? `${formatThreshold(rCheck.current_cp, unit)}${unit}` : '',
    rdNeededCp:
      rCheck.needed_cp != null ? `${formatThreshold(rCheck.needed_cp, unit)}${unit}` : '',
    rdHasGapValue: rCheck.cp_gap_watts != null,
    rdGapValue:
      rCheck.cp_gap_watts != null
        ? `${rCheck.cp_gap_watts > 0 ? '+' : ''}${
            isPace
              ? formatPace(Math.abs(rCheck.cp_gap_watts))
              : Math.round(rCheck.cp_gap_watts)
          }${unit}`
        : '',
    rdHasTrendNote: !!rCheck.trend_note,
    rdTrendNote: rCheck.trend_note ?? '',
    rdHasRealistic:
      !!rCheck.realistic_targets &&
      (rCheck.severity === 'behind' || rCheck.severity === 'unlikely'),
    rdComfortable: rCheck.realistic_targets
      ? formatTime(rCheck.realistic_targets.comfortable)
      : '',
    rdStretch: rCheck.realistic_targets ? formatTime(rCheck.realistic_targets.stretch) : '',

    // No-target trend card (only renders when hasTarget is false).
    rdShowTrendOnly: !hasTarget && !!rCheck.trend_note,
  };
}

function buildCpMilestoneState(
  response: GoalResponse,
  unit: string,
  isPace: boolean,
): Partial<GoalState> {
  const rc = response.race_countdown;
  const rCheck = rc.reality_check;
  const currentCp = response.latest_cp;
  const targetCp = rc.target_cp ?? null;
  const distLabel = rc.distance_label ?? 'Race';
  const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const severityClass = severityAccent(rCheck.severity);

  // Pace progress is inverted: lower pace = faster, so "progress" toward
  // a faster target is target/current, not current/target.
  let progressPct = 0;
  if (currentCp != null && targetCp != null && targetCp > 0 && currentCp > 0) {
    progressPct = isPace
      ? Math.min(100, Math.max(0, (targetCp / currentCp) * 100))
      : Math.min(100, Math.max(0, (currentCp / targetCp) * 100));
  }

  const milestoneSrc: Milestone[] = rc.milestones ?? [];
  const milestones: MilestoneRow[] = milestoneSrc.map((m) => {
    const isCurrent = currentCp != null && m.cp === currentCp;
    return {
      cp: m.cp,
      cpDisplay: `${m.cp}${unit}`,
      marathon: m.marathon,
      reached: m.reached,
      isCurrent,
      iconClass: m.reached ? 'goal-ms-icon goal-ms-icon--reached' : 'goal-ms-icon',
      rowClass: isCurrent ? 'goal-ms-row goal-ms-row--current' : 'goal-ms-row',
    };
  });

  return {
    cmDistLabel: distLabel,
    cmHero: hasTimeTarget
      ? `Building toward ${formatTime(rc.target_time_sec as number)} ${distLabel}`
      : `${distLabel} Progress`,
    cmHasPredicted: rc.predicted_time_sec != null,
    cmPredictedTime: rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—',
    cmHasTarget: hasTimeTarget,
    cmTargetTime: hasTimeTarget ? formatTime(rc.target_time_sec as number) : '',
    cmHasCpProgress: targetCp != null,
    cmCurrentCp: currentCp != null ? formatThreshold(currentCp, unit) : '—',
    cmTargetCp: targetCp != null ? formatThreshold(targetCp, unit) : '',
    cmThresholdUnit: unit,
    cmProgressPctLabel: `${progressPct.toFixed(0)}%`,
    cmProgressBarPct: progressPct,
    cmStatusText: statusBadgeText(rc.status),
    cmStatusAccent: severityClass,
    cmHasMilestones: milestones.length > 0,
    cmMilestones: milestones,
    cmHasAssessment: !!rCheck.assessment,
    cmAssessment: rCheck.assessment ?? '',
    cmAssessmentAccent: severityClass,
    cmHasEstimatedMonths: rc.estimated_months != null,
    cmEstimatedMonths:
      rc.estimated_months != null ? `${rc.estimated_months.toFixed(1)} months` : '',
    cmHasTrendNote: !!rCheck.trend_note,
    cmTrendNote: rCheck.trend_note ?? '',
  };
}

function buildContinuousState(
  response: GoalResponse,
  unit: string,
  isPace: boolean,
): Partial<GoalState> {
  const rc = response.race_countdown;
  const rCheck = rc.reality_check;
  const currentCp = response.latest_cp;
  const trend = rc.cp_trend_summary;
  const distLabel = rc.distance_label ?? 'Marathon';
  const severityClass = severityAccent(rCheck.severity);

  let slopeText = '';
  if (trend && trend.slope_per_month !== 0) {
    const sign = trend.slope_per_month > 0 ? '+' : '';
    const formatted = isPace
      ? formatPace(Math.abs(trend.slope_per_month))
      : trend.slope_per_month.toFixed(1);
    slopeText = `(${sign}${formatted}${unit}/mo)`;
  }

  return {
    ctCurrentCp: currentCp != null ? formatThreshold(currentCp, unit) : '—',
    ctHasCurrentCp: currentCp != null,
    ctThresholdUnit: unit,
    ctHasTrend: trend != null,
    ctTrendDirection: trend ? trendDirectionLabel(trend.direction) : 'Flat',
    ctTrendAccent: severityClass,
    ctHasSlope: !!slopeText,
    ctSlopeText: slopeText,
    ctHasPredicted: rc.predicted_time_sec != null,
    ctPredictedTime: rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—',
    ctDistLabel: distLabel,
    ctHasAssessment: !!rCheck.assessment && !!rCheck.trend_note,
    ctAssessment: rCheck.assessment ?? '',
    ctAssessmentAccent: severityClass,
    ctHasTrendNote: !!rCheck.trend_note,
    ctTrendNote: rCheck.trend_note ?? '',
  };
}

Page({
  data: { ...initialData },

  onLoad() {
    const tc = themeClassName();
    this.setData({ themeClass: tc, chartTheme: tc === 'theme-light' ? 'light' : 'dark' });
    void this.refetch();
  },

  onShow() {
    applyThemeChrome();
    const tabBar = (this as { getTabBar?: () => { setData: (d: unknown) => void } | null })
      .getTabBar?.();
    tabBar?.setData({ selected: 3 });
  },

  onShareAppMessage() {
    // Dynamic per-mode share so friends see the actual countdown / target.
    // Each branch is fully localized — no Chinese-mixed-into-English copy.
    const mode = this.data.mode as string;
    const locale = detectShareLocale();
    const days = (this.data.rdDaysLeft as string) || '';
    const dist = (this.data.rdDistLabel as string) || '';
    const predicted = (this.data.rdPredictedTime as string) || '';
    if (mode === 'race_date' && days && dist) {
      const hasPred = predicted && predicted !== '—';
      const title =
        locale === 'zh'
          ? `距离比赛: ${days} 天 · ${dist}${hasPred ? ` · 预计 ${predicted}` : ''}`
          : `Race countdown: ${days} days · ${dist}${hasPred ? ` · predicted ${predicted}` : ''}`;
      return buildShareMessage(title, '/pages/goal/index');
    }
    if (mode === 'cp_milestone') {
      const cur = this.data.cmCurrentCp as string;
      const target = this.data.cmTargetCp as string;
      const unit = this.data.cmThresholdUnit as string;
      if (cur && target) {
        const title =
          locale === 'zh'
            ? `冲击目标 ${target}${unit} (当前 ${cur}${unit})`
            : `Targeting ${target}${unit} (${cur}${unit} now)`;
        return buildShareMessage(title, '/pages/goal/index');
      }
    }
    if (mode === 'continuous') {
      const cur = this.data.ctCurrentCp as string;
      const unit = this.data.ctThresholdUnit as string;
      if (cur) {
        const title =
          locale === 'zh' ? `当前体能: ${cur}${unit}` : `Current fitness: ${cur}${unit}`;
        return buildShareMessage(title, '/pages/goal/index');
      }
    }
    return getShareMessage(locale, '/pages/goal/index');
  },

  onShareTimeline() {
    const locale = detectShareLocale();
    const fallback =
      locale === 'zh' ? '像专业选手一样训练' : 'Train like a pro. Whatever your level.';
    const days = (this.data.rdDaysLeft as string) || '';
    const dist = (this.data.rdDistLabel as string) || '';
    const hasRace = this.data.mode === 'race_date' && days && dist;
    const title = hasRace
      ? locale === 'zh'
        ? `${days} 天 · ${dist}`
        : `${days} days · ${dist}`
      : fallback;
    return buildTimelineMessage(title);
  },

  onScrollRefresh() {
    this.setData({ refreshing: true });
    void this.refetch().finally(() => this.setData({ refreshing: false }));
  },

  onRetry() {
    void this.refetch();
  },

  toggleNotePrediction() {
    this.setData({ notePredictionExpanded: !this.data.notePredictionExpanded });
  },

  toggleNoteUltra() {
    this.setData({ noteUltraExpanded: !this.data.noteUltraExpanded });
  },

  onTapPredictionSource() {
    if (this.data.notePredictionUrl) copyUrlToClipboard(this.data.notePredictionUrl);
  },

  onTapUltraSource() {
    if (this.data.noteUltraUrl) copyUrlToClipboard(this.data.noteUltraUrl);
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      const response = await apiGet<GoalResponse>('/api/goal');
      this.setData(buildState(response, this.data.themeClass) as Record<string, unknown>);
    } catch (e) {
      const err = e as Partial<ApiError>;
      // The api-client throws UNAUTHENTICATED *and* schedules a reLaunch.
      // Skip the error UI so the page doesn't flash the raw code before
      // it's unmounted; the toast in api-client already explains.
      if (err?.code === 'UNAUTHENTICATED') return;
      const detail = err?.detail ?? String(e);
      this.setData({ loading: false, errorMessage: detail, hasResponse: false });
    }
  },
});
