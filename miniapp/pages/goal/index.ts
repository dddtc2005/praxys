import { setTabBarSelected } from '../../utils/tabbar';
import type { IAppOption } from '../../app';
import { apiGet, apiPut } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import type { GoalResponse, AiInsight, AiInsightFinding } from '../../types/api';
import { formatTime, formatPace } from '../../utils/format';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import {
  buildShareMessage,
  buildTimelineMessage,
  detectShareLocale,
  getShareMessage,
} from '../../utils/share';
import { copyUrlToClipboard } from '../../utils/markdown';
import { t, tFmt } from '../../utils/i18n';
import { fetchInsight, localizedInsight } from '../../utils/insights';

// ---- Editor distance choices (unchanged) ----
type DistanceKey = '5k' | '10k' | 'half' | 'marathon' | '50k' | '50mi' | '100k' | '100mi';

interface DistanceChoice {
  key: DistanceKey;
  label: string;
  placeholder: string;
}

// ---- Coach receipt types (mirrors today page local types) ----
interface CoachFindingRow {
  id: string;
  marker: string;
  tone: AiInsightFinding['type'];
  text: string;
}

interface CoachRecRow {
  index: string;
  text: string;
}

interface CoachReceipt {
  stamp: string;
  headline: string;
  hasFindings: boolean;
  findings: CoachFindingRow[];
  hasRecommendations: boolean;
  recommendations: CoachRecRow[];
  attribution: string;
}

interface CoachTranslations {
  mark: string;
  aria: string;
  findings: string;
  recommendations: string;
}

// ---- Strip cell ----
interface StripCell {
  id: string;
  label: string;
  value: string;
  sub: string;
  accent: string;
}

// ---- Series payload for CP trend chart ----
interface SeriesPayload {
  label: string;
  color: string;
  values: (number | null)[];
  fill?: boolean;
}

// ---- Editor snapshot ----
interface EditorSnapshot {
  type: 'race' | 'continuous';
  distanceIndex: number;
  raceDate: string;
  targetTimeSec: number;
}

// ---- Science-note URL constants ----
const SCIENCE_POWER_URL = 'https://help.stryd.com/en/articles/6879547-race-power-calculator';
const SCIENCE_PACE_URL =
  'https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html';
const SCIENCE_ULTRA_URL =
  'https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html';
const ULTRA_DISTANCES = new Set(['50k', '50mi', '100k', '100mi']);

// ---- Translations ----

function buildGoalTr() {
  return {
    navTitle: t('Goal'),
    failedToLoad: t('Failed to load'),
    howCalculated: t('How this is calculated'),
    ultraCaveat: t('Ultra distance caveat'),
    sourceTapCopy: t('Source — tap to copy URL'),
    discussionTapCopy: t('Discussion — tap to copy URL'),
    cpTrend: t('CP trend'),
    realisticTargets: t('Realistic alternative targets'),
    comfortable: t('Comfortable'),
    stretch: t('Stretch'),
    changeGoal: t('Change Goal'),
    editorTitle: t('Set Your Goal'),
    goalType: t('Goal type'),
    raceGoal: t('Race Goal'),
    raceGoalDesc: t('Train toward a specific race date'),
    continuousGoal: t('Continuous'),
    continuousGoalDesc: t('Build fitness over time'),
    distance: t('Distance'),
    raceDate: t('Race Date'),
    pickDate: t('Pick a date'),
    targetTime: t('Target Time'),
    optional: t('optional'),
    cancel: t('Cancel'),
    save: t('Save Goal'),
    saving: t('Saving…'),
    raceDateRequired: t('Race date is required'),
    failedToSave: t('Failed to save goal'),
    targetTimeHint: t('0:00:00 = no target time'),
    discardConfirm: t('Discard'),
    keepEditing: t('Keep editing'),
    discardPrompt: t('Discard changes?'),
  };
}

function buildCoachTr(): CoachTranslations {
  return {
    mark: 'PRAXYS COACH',
    aria: t('Praxys Coach insight'),
    findings: t('Findings'),
    recommendations: t('Recommendations'),
  };
}

// ---- GoalState ----

interface GoalState {
  themeClass: string;
  chartTheme: 'light' | 'dark';
  loading: boolean;
  errorMessage: string;
  hasResponse: boolean;
  refreshing: boolean;
  mode: GoalResponse['race_countdown']['mode'];

  goalEyebrow: string;
  goalHeadline: string;
  showStatusBadge: boolean;
  statusText: string;
  statusAccent: string;
  stripCells: StripCell[];
  showRealisticTargets: boolean;
  rdComfortable: string;
  rdStretch: string;
  hasRationale: boolean;
  rationaleText: string;

  hasCoach: boolean;
  coach: CoachReceipt | null;
  coachTr: CoachTranslations | null;

  hasCpTrend: boolean;
  cpTrendDates: string[];
  cpTrendSeries: SeriesPayload[];
  cpTrendReferenceY: number | null;
  cpTrendUnit: string;

  notePredictionText: string;
  notePredictionUrl: string;
  notePredictionExpanded: boolean;
  hasUltraNote: boolean;
  noteUltraText: string;
  noteUltraUrl: string;
  noteUltraExpanded: boolean;

  editorOpen: boolean;
  editorType: 'race' | 'continuous';
  editorDistanceLabels: string[];
  editorDistanceIndex: number;
  editorRaceDate: string;
  editorTodayIso: string;
  editorTimeRange: string[][];
  editorTimeParts: number[];
  editorTargetDisplay: string;
  editorError: string;
  editorSaving: boolean;
  editorDirty: boolean;
  editorConfirmDiscard: boolean;
}

// ---- Distance helpers ----

function buildDistanceChoices(): DistanceChoice[] {
  return [
    { key: '5k', label: t('5K'), placeholder: 'e.g. 20:00' },
    { key: '10k', label: t('10K'), placeholder: 'e.g. 42:00' },
    { key: 'half', label: t('Half'), placeholder: 'e.g. 1:30:00' },
    { key: 'marathon', label: t('Marathon'), placeholder: 'e.g. 3:00:00' },
    { key: '50k', label: t('50K'), placeholder: 'e.g. 4:30:00' },
    { key: '50mi', label: t('50 Mi'), placeholder: 'e.g. 8:00:00' },
    { key: '100k', label: t('100K'), placeholder: 'e.g. 12:00:00' },
    { key: '100mi', label: t('100 Mi'), placeholder: 'e.g. 24:00:00' },
  ];
}

function todayIso(): string {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function buildTimeRange(): string[][] {
  const hours = Array.from({ length: 48 }, (_, i) => `${i}h`);
  const minutes = Array.from({ length: 60 }, (_, i) => `${String(i).padStart(2, '0')}m`);
  const seconds = Array.from({ length: 60 }, (_, i) => `${String(i).padStart(2, '0')}s`);
  return [hours, minutes, seconds];
}

function secondsToTimeParts(sec: number | null | undefined): [number, number, number] {
  if (!sec || sec <= 0) return [0, 0, 0];
  const h = Math.min(47, Math.floor(sec / 3600));
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return [h, m, s];
}

function timePartsToSeconds(parts: number[]): number {
  const [h = 0, m = 0, s = 0] = parts;
  return h * 3600 + m * 60 + s;
}

function timePartsToDisplay(parts: number[]): string {
  const [h = 0, m = 0, s = 0] = parts;
  if (h === 0 && m === 0 && s === 0) return '—';
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// ---- Formatting / severity ----

function formatThreshold(value: number, unit: string): string {
  if (unit === '/km') return formatPace(value);
  return `${Math.round(value)}`;
}

function severityAccent(severity: string): string {
  switch (severity) {
    case 'on_track': return 'ts-primary';
    case 'close': return 'ts-warning';
    case 'behind':
    case 'unlikely': return 'ts-destructive';
    default: return '';
  }
}

function statusBadgeText(status: string): string {
  return t(status).toUpperCase();
}

// ---- Science note helpers ----

const defaultPowerNote = () =>
  t('Predicted using Stryd race power model (5K at 103.8% CP, marathon at 89.9% CP).');
const defaultPaceNote = () =>
  t("Predicted using Riegel's formula (T₂ = T₁ × (D₂/D₁)^1.06), treating threshold pace as ~10K effort.");
const ultraNoteText = () =>
  t(
    "Ultra distance power fractions (50K+) are estimates with limited research backing. " +
      "Riegel's exponent is validated only up to marathon distance. Predictions beyond marathon " +
      'carry significantly higher uncertainty due to factors like fueling, terrain, heat, and pacing ' +
      'strategy that dominate ultra performance but are not captured by power/pace models.',
  );

interface PredictionNote { text: string; url: string; }

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
    return { text: defaultPowerNote(), url: SCIENCE_POWER_URL };
  }
  return { text: defaultPaceNote(), url: SCIENCE_PACE_URL };
}

// ---- Coach receipt builder ----

function timeAgo(isoDate: string, locale: string): string {
  const diffMs = Date.now() - new Date(isoDate).getTime();
  if (Number.isNaN(diffMs)) return '';
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return locale === 'zh' ? `${diffMin}分钟前` : `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return locale === 'zh' ? `${diffH}小时前` : `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return locale === 'zh' ? `${diffD}天前` : `${diffD}d ago`;
}

function buildCoachReceipt(insight: AiInsight, locale: 'en' | 'zh'): CoachReceipt {
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
  return {
    stamp: insight.generated_at ? timeAgo(insight.generated_at, locale) : '',
    headline: view.headline,
    hasFindings: findings.length > 0,
    findings,
    hasRecommendations: recommendations.length > 0,
    recommendations,
    attribution: '',
  };
}

// ---- Eyebrow builder ----

function buildGoalEyebrow(
  rc: GoalResponse['race_countdown'],
  mode: string,
  distLabel: string,
  hasTimeTarget: boolean,
): string {
  const modeLabel =
    mode === 'race_date' ? t('Race') : mode === 'cp_milestone' ? t('Goal') : t('Tracking');

  if (mode === 'race_date') {
    const parts = [modeLabel];
    if (rc.race_date) parts.push(rc.race_date);
    if (hasTimeTarget && rc.target_time_sec) parts.push(formatTime(rc.target_time_sec));
    return parts.join(' · ');
  }
  if (mode === 'cp_milestone') {
    const goalLabel =
      hasTimeTarget && rc.target_time_sec
        ? `${formatTime(rc.target_time_sec)} ${distLabel}`
        : distLabel;
    return `${modeLabel} · ${goalLabel}`;
  }
  return `${modeLabel} · ${distLabel}`;
}

// ---- Headline builder ----

function buildGoalHeadline(
  rc: GoalResponse['race_countdown'],
  mode: string,
  currentCp: number | null,
  targetCp: number | null,
  unit: string,
  abbrev: string,
  isPace: boolean,
  distLabel: string,
): string {
  if (mode === 'race_date') {
    const days = rc.days_left ?? 0;
    const predicted =
      rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—';
    const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
    if (hasTimeTarget) {
      return tFmt(
        '{0} days to race day. Today\'s prediction is {1} against a target of {2}.',
        `${days}`, predicted, formatTime(rc.target_time_sec as number),
      );
    }
    return tFmt('{0} days to race day. Today\'s prediction is {1}.', `${days}`, predicted);
  }

  if (mode === 'cp_milestone') {
    const currentStr = currentCp != null ? formatThreshold(currentCp, unit) : '—';
    const targetStr = targetCp != null ? formatThreshold(targetCp, unit) : '—';
    const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
    if (hasTimeTarget) {
      return tFmt(
        'Building toward {0} {1}. Current {2} {3}{4}, need {5}{4}.',
        formatTime(rc.target_time_sec as number), distLabel, abbrev, currentStr, unit, targetStr,
      );
    }
    return tFmt(
      'Building toward {0}. Current {1} {2}{3}, need {4}{3}.',
      distLabel, abbrev, currentStr, unit, targetStr,
    );
  }

  // continuous / none
  const predicted = rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : null;
  const trend = rc.cp_trend_summary;
  const dirLabel = trend
    ? trend.direction === 'rising'
      ? t('Rising').toLowerCase()
      : trend.direction === 'falling'
        ? t('Falling').toLowerCase()
        : t('Flat').toLowerCase()
    : t('Flat').toLowerCase();

  let slopeStr: string | null = null;
  if (trend && trend.slope_per_month !== 0) {
    const sign = trend.slope_per_month > 0 ? '+' : '';
    const formatted = isPace
      ? formatPace(Math.abs(trend.slope_per_month))
      : trend.slope_per_month.toFixed(1);
    slopeStr = `${sign}${formatted}${unit}/mo`;
  }

  if (predicted && slopeStr) {
    return tFmt(
      'Today\'s {0} prediction is {1}. {2} is {3} at {4}.',
      distLabel, predicted, abbrev, dirLabel, slopeStr,
    );
  }
  if (predicted) {
    return tFmt(
      'Today\'s {0} prediction is {1}. {2} is {3}.',
      distLabel, predicted, abbrev, dirLabel,
    );
  }
  return tFmt('{0} is {1}. Add more activities for a race-time prediction.', abbrev, dirLabel);
}

// ---- Strip cells builder ----

function buildStripCells(
  rc: GoalResponse['race_countdown'],
  mode: string,
  currentCp: number | null,
  unit: string,
  abbrev: string,
  isPace: boolean,
  distLabel: string,
): StripCell[] {
  const cells: StripCell[] = [];
  const rCheck = rc.reality_check;
  const targetCp = rc.target_cp ?? null;
  const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;

  if (mode === 'race_date') {
    cells.push({
      id: 'days', label: t('Days left'),
      value: rc.days_left != null ? `${rc.days_left}` : '—', sub: '', accent: '',
    });
    cells.push({
      id: 'predicted', label: t('Predicted'),
      value: rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—',
      sub: distLabel, accent: '',
    });
    if (hasTimeTarget) {
      cells.push({
        id: 'target', label: t('Target'),
        value: formatTime(rc.target_time_sec as number), sub: distLabel, accent: '',
      });
    }
    cells.push({
      id: 'current_cp', label: `${t('current')} ${abbrev}`,
      value: currentCp != null ? formatThreshold(currentCp, unit) : '—', sub: unit, accent: '',
    });
    if (rCheck.needed_cp != null) {
      cells.push({
        id: 'needed_cp', label: `${t('Needed')} ${abbrev}`,
        value: formatThreshold(rCheck.needed_cp, unit), sub: unit, accent: '',
      });
    }
    if (rCheck.cp_gap_watts != null) {
      cells.push({
        id: 'gap', label: t('Gap'),
        value: `${rCheck.cp_gap_watts > 0 ? '+' : ''}${
          isPace
            ? formatPace(Math.abs(rCheck.cp_gap_watts))
            : Math.round(rCheck.cp_gap_watts)
        }`,
        sub: unit, accent: severityAccent(rCheck.severity),
      });
    }
  } else if (mode === 'cp_milestone') {
    const gap = currentCp != null && targetCp != null ? targetCp - currentCp : null;
    cells.push({
      id: 'gap', label: t('Gap'),
      value: gap != null
        ? `${gap > 0 ? '+' : ''}${formatThreshold(Math.abs(gap), unit)}`
        : '—',
      sub: unit,
      accent: gap == null ? '' : gap > 0 ? 'ts-warning' : 'ts-primary',
    });
    cells.push({
      id: 'predicted', label: t('Predicted'),
      value: rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—',
      sub: distLabel, accent: '',
    });
    cells.push({
      id: 'to_target', label: t('To target'),
      value: rc.estimated_months != null ? rc.estimated_months.toFixed(1) : '—',
      sub: rc.estimated_months != null ? t('months') : '',
      accent: '',
    });
  } else {
    // continuous / none
    const trend = rc.cp_trend_summary;
    cells.push({
      id: 'current_cp', label: `${t('current')} ${abbrev}`,
      value: currentCp != null ? formatThreshold(currentCp, unit) : '—', sub: unit, accent: '',
    });
    const dirLabel = trend
      ? trend.direction === 'rising' ? t('Rising')
        : trend.direction === 'falling' ? t('Falling') : t('Flat')
      : t('Flat');
    let slopeSub = '';
    if (trend && trend.slope_per_month !== 0) {
      const sign = trend.slope_per_month > 0 ? '+' : '';
      const formatted = isPace
        ? formatPace(Math.abs(trend.slope_per_month))
        : trend.slope_per_month.toFixed(1);
      slopeSub = `${sign}${formatted}${unit}/mo`;
    }
    cells.push({
      id: 'direction', label: t('Direction'),
      value: dirLabel, sub: slopeSub, accent: severityAccent(rCheck.severity),
    });
    if (rc.predicted_time_sec != null) {
      cells.push({
        id: 'predicted_cont', label: t('Predicted'),
        value: formatTime(rc.predicted_time_sec), sub: distLabel, accent: '',
      });
    }
  }
  return cells;
}

// ---- Full render state builder ----

function buildGoalState(
  response: GoalResponse,
  insight: AiInsight | null,
  locale: 'en' | 'zh',
  themeClass: string,
): Partial<GoalState> {
  const rc = response.race_countdown;
  const rCheck = rc.reality_check;
  const display = response.display;
  const unit = display?.threshold_unit ?? 'W';
  const abbrev = display?.threshold_abbrev ?? 'CP';
  const isPace = unit === '/km';
  const currentCp = response.latest_cp;
  const targetCp = rc.target_cp ?? null;
  const distLabel = t(rc.distance_label ?? 'Marathon');
  const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const mode = rc.mode;

  const trend = response.cp_trend;
  const hasCpTrend = !!trend && trend.values.length >= 2;

  const note = predictionNote(response);
  const isUltra = !!rc.distance && ULTRA_DISTANCES.has(rc.distance);

  let coach: CoachReceipt | null = null;
  try {
    if (insight) coach = buildCoachReceipt(insight, locale);
  } catch (e) {
    console.warn('[goal] coach receipt build failed; suppressing:', e);
  }
  const hasCoach = coach != null;

  const severity = rCheck.severity;
  const showStatusBadge = severity !== 'unknown';

  const goalEyebrow = buildGoalEyebrow(rc, mode, distLabel, hasTimeTarget);
  const goalHeadline = buildGoalHeadline(rc, mode, currentCp, targetCp, unit, abbrev, isPace, distLabel);
  const stripCells = buildStripCells(rc, mode, currentCp, unit, abbrev, isPace, distLabel);

  const showRealisticTargets =
    mode === 'race_date' &&
    !!rCheck.realistic_targets &&
    (severity === 'behind' || severity === 'unlikely');

  return {
    themeClass,
    loading: false,
    errorMessage: '',
    hasResponse: true,
    mode,

    goalEyebrow,
    goalHeadline,
    showStatusBadge,
    statusText: statusBadgeText(severity),
    statusAccent: severityAccent(severity),
    stripCells,
    showRealisticTargets,
    rdComfortable: rCheck.realistic_targets
      ? formatTime(rCheck.realistic_targets.comfortable)
      : '',
    rdStretch: rCheck.realistic_targets ? formatTime(rCheck.realistic_targets.stretch) : '',
    hasRationale: !hasCoach && !!rCheck.trend_note,
    rationaleText: rCheck.trend_note ?? '',

    hasCoach,
    coach,
    coachTr: hasCoach ? buildCoachTr() : null,

    hasCpTrend,
    cpTrendDates: hasCpTrend ? trend.dates : [],
    cpTrendSeries: hasCpTrend
      ? [{ label: abbrev, color: '#00ff87', values: trend.values, fill: true }]
      : [],
    cpTrendReferenceY: targetCp,
    cpTrendUnit: isPace ? '' : unit,

    notePredictionText: note.text,
    notePredictionUrl: note.url,
    hasUltraNote: isUltra,
    noteUltraText: isUltra ? ultraNoteText() : '',
  };
}

// ---- Initial page data ----

const DISTANCE_CHOICES = buildDistanceChoices();

const initialData: GoalState = {
  themeClass: getApp<IAppOption>().globalData.themeClass,
  chartTheme: 'light',
  loading: true,
  errorMessage: '',
  hasResponse: false,
  refreshing: false,
  mode: 'none',

  goalEyebrow: '',
  goalHeadline: '',
  showStatusBadge: false,
  statusText: '',
  statusAccent: '',
  stripCells: [],
  showRealisticTargets: false,
  rdComfortable: '',
  rdStretch: '',
  hasRationale: false,
  rationaleText: '',

  hasCoach: false,
  coach: null,
  coachTr: null,

  hasCpTrend: false,
  cpTrendDates: [],
  cpTrendSeries: [],
  cpTrendReferenceY: null,
  cpTrendUnit: '',

  notePredictionText: '',
  notePredictionUrl: '',
  notePredictionExpanded: false,
  hasUltraNote: false,
  noteUltraText: '',
  noteUltraUrl: SCIENCE_ULTRA_URL,
  noteUltraExpanded: false,

  editorOpen: false,
  editorType: 'race',
  editorDistanceLabels: DISTANCE_CHOICES.map((d) => d.label),
  editorDistanceIndex: 3,
  editorRaceDate: '',
  editorTodayIso: todayIso(),
  editorTimeRange: buildTimeRange(),
  editorTimeParts: [0, 0, 0],
  editorTargetDisplay: '—',
  editorError: '',
  editorSaving: false,
  editorDirty: false,
  editorConfirmDiscard: false,
};

// ---- Page ----

Page({
  data: { ...initialData, tr: buildGoalTr() },

  onLoad() {
    const tc = themeClassName();
    this.setData({ themeClass: tc, chartTheme: tc === 'theme-light' ? 'light' : 'dark', tr: buildGoalTr() });
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
      this.setData({ tr: buildGoalTr() });
      void this.refetch();
    }
    applyThemeChrome();
    setTabBarSelected(this, 3);
  },

  onShareAppMessage() {
    const locale = detectShareLocale();
    const eyebrow = (this.data.goalEyebrow as string) || '';
    const headline = (this.data.goalHeadline as string) || '';
    const title = eyebrow && headline ? `${eyebrow} — ${headline}` : headline || eyebrow;
    if (title) return buildShareMessage(title.slice(0, 100), '/pages/goal/index');
    return getShareMessage(locale, '/pages/goal/index');
  },

  onShareTimeline() {
    const locale = detectShareLocale();
    const eyebrow = (this.data.goalEyebrow as string) || '';
    const fallback =
      locale === 'zh' ? '像专业选手一样训练，无论水平高低。' : 'Train like a pro. Whatever your level.';
    return buildTimelineMessage(eyebrow || fallback);
  },

  onScrollRefresh() {
    this.setData({ refreshing: true });
    void this.refetch().finally(() => this.setData({ refreshing: false }));
  },

  onRetry() { void this.refetch(); },

  toggleNotePrediction() {
    this.setData({ notePredictionExpanded: !this.data.notePredictionExpanded });
  },

  toggleNoteUltra() {
    this.setData({ noteUltraExpanded: !this.data.noteUltraExpanded });
  },

  onTapPredictionSource() {
    if (this.data.notePredictionUrl) copyUrlToClipboard(this.data.notePredictionUrl as string);
  },

  onTapUltraSource() {
    if (this.data.noteUltraUrl) copyUrlToClipboard(this.data.noteUltraUrl as string);
  },

  onOpenEditor() {
    const freshTr = buildGoalTr();
    this.setData({ tr: freshTr });
    const cached = (this.data as { _response?: GoalResponse })._response;
    const goal = (cached?.race_countdown ?? null) as
      | { distance?: string | null; race_date?: string | null; target_time_sec?: number | null }
      | null;
    const distanceKey = (goal?.distance as DistanceKey | undefined) ?? 'marathon';
    const idx = Math.max(0, DISTANCE_CHOICES.findIndex((d) => d.key === distanceKey));
    const editorType: 'race' | 'continuous' = goal?.race_date ? 'race' : 'continuous';
    const targetTimeSec =
      goal?.target_time_sec && goal.target_time_sec > 0 ? goal.target_time_sec : 0;
    const timeParts = secondsToTimeParts(targetTimeSec);
    const editorRaceDate = goal?.race_date ?? '';
    (this.data as { _editorInitial?: EditorSnapshot })._editorInitial = {
      type: editorType, distanceIndex: idx, raceDate: editorRaceDate, targetTimeSec,
    };
    this.setData({
      editorOpen: true, editorType, editorDistanceIndex: idx, editorRaceDate,
      editorTodayIso: todayIso(), editorTimeParts: timeParts,
      editorTargetDisplay: timePartsToDisplay(timeParts),
      editorError: '', editorSaving: false, editorDirty: false, editorConfirmDiscard: false,
    });
  },

  onCloseEditor() {
    if (this.data.editorSaving) return;
    if (!this.data.editorDirty) {
      this.setData({ editorOpen: false, editorError: '', editorConfirmDiscard: false });
      return;
    }
    this.setData({ editorConfirmDiscard: true });
  },

  onDiscardConfirm() {
    this.setData({ editorOpen: false, editorError: '', editorConfirmDiscard: false });
  },

  onDiscardKeep() { this.setData({ editorConfirmDiscard: false }); },

  onPickEditorType(e: WechatMiniprogram.TouchEvent) {
    const type = e.currentTarget.dataset.type as 'race' | 'continuous' | undefined;
    if (!type) return;
    this.setData({ editorType: type });
    this.recomputeEditorDirty();
  },

  onPickEditorDistance(e: WechatMiniprogram.PickerChange) {
    const idx = Number(e.detail.value);
    if (Number.isNaN(idx)) return;
    this.setData({
      editorDistanceIndex: idx,
      editorTargetPlaceholder: DISTANCE_CHOICES[idx]?.placeholder ?? '',
    });
    this.recomputeEditorDirty();
  },

  onPickEditorRaceDate(e: WechatMiniprogram.PickerChange) {
    this.setData({ editorRaceDate: String(e.detail.value) });
    this.recomputeEditorDirty();
  },

  onPickEditorTargetTime(e: WechatMiniprogram.PickerChange) {
    const parts = (e.detail.value as number[]) || [0, 0, 0];
    this.setData({ editorTimeParts: parts, editorTargetDisplay: timePartsToDisplay(parts) });
    this.recomputeEditorDirty();
  },

  recomputeEditorDirty() {
    const snap = (this.data as { _editorInitial?: EditorSnapshot })._editorInitial;
    if (!snap) return;
    const dirty =
      (this.data.editorType as string) !== snap.type ||
      (this.data.editorDistanceIndex as number) !== snap.distanceIndex ||
      (this.data.editorRaceDate as string) !== snap.raceDate ||
      timePartsToSeconds(this.data.editorTimeParts as number[]) !== snap.targetTimeSec;
    if (dirty !== this.data.editorDirty) this.setData({ editorDirty: dirty });
  },

  async onSaveEditor() {
    if (!this.data.editorDirty || this.data.editorSaving) return;
    const tr = this.data.tr as ReturnType<typeof buildGoalTr>;
    const editorType = this.data.editorType as 'race' | 'continuous';
    const editorDistanceIndex = this.data.editorDistanceIndex as number;
    const editorRaceDate = this.data.editorRaceDate as string;
    if (editorType === 'race' && !editorRaceDate) {
      this.setData({ editorError: tr.raceDateRequired });
      return;
    }
    const targetTimeSec = timePartsToSeconds(this.data.editorTimeParts as number[]);
    this.setData({ editorSaving: true, editorError: '' });
    const distance = DISTANCE_CHOICES[editorDistanceIndex]?.key ?? 'marathon';
    try {
      await apiPut('/api/settings', {
        goal: { race_date: editorType === 'race' ? editorRaceDate : '', distance, target_time_sec: targetTimeSec },
      });
      this.setData({ editorOpen: false, editorSaving: false });
      void this.refetch();
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') return;
      this.setData({ editorSaving: false, editorError: err?.detail ?? tr.failedToSave });
    }
  },

  async refetch() {
    this.setData({ loading: true, errorMessage: '' });
    try {
      const locale = (getApp<IAppOption>().globalData.locale ?? 'en') as 'en' | 'zh';
      const [response, insight] = await Promise.all([
        apiGet<GoalResponse>('/api/goal'),
        fetchInsight('race_forecast').catch((e) => {
          console.warn('[goal] race_forecast fetch failed; suppressing coach receipt:', e);
          return null;
        }),
      ]);
      this.setData({
        ...(buildGoalState(response, insight, locale, this.data.themeClass) as Record<string, unknown>),
        _response: response,
      } as Record<string, unknown>);
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') {
        this.setData({ loading: false });
        return;
      }
      this.setData({ loading: false, errorMessage: err?.detail ?? String(e), hasResponse: false });
    }
  },
});
