// API response types

export type TrainingBase = 'power' | 'hr' | 'pace';
export type SciencePillar = 'load' | 'recovery' | 'prediction' | 'zones';

/** Build version of the running ``api/main.py``. The backend always
 * returns a non-empty string (``"develop"`` is the local-dev fallback),
 * so consumers don't need to handle a missing field. */
export interface VersionResponse {
  version: string;
}

export interface TsbZoneConfig {
  min: number | null;
  max: number | null;
  /** Stable English identifier for client-side lookups (e.g. zone-insight
   * dictionaries). `label` is the localized display string and changes per
   * locale; `key` is invariant. Optional because older API responses or
   * custom label sets may omit it — clients should fall back to `label`. */
  key?: string;
  label: string;
  color: string;
}

export interface TheorySummary {
  id: string;
  name: string;
  description: string;
  simple_description: string;
  advanced_description: string;
  author: string;
  citations: Record<string, unknown>[];
  params?: Record<string, unknown>;
  tsb_zones?: TsbZoneConfig[];
}

export interface PillarRecommendation {
  pillar: SciencePillar;
  recommended_id: string;
  reason: string;
  confidence: 'strong' | 'moderate' | 'weak';
}

export interface ScienceResponse {
  active: Partial<Record<SciencePillar, TheorySummary>>;
  active_labels: string;
  available: Record<SciencePillar, TheorySummary[]>;
  label_sets: { id: string; name: string }[];
  recommendations: PillarRecommendation[];
}
export type PlatformName = 'garmin' | 'strava' | 'stryd' | 'oura' | 'coros';
export type PlanSourceName = PlatformName | 'ai';
export type DataCategory = 'activities' | 'recovery' | 'fitness' | 'plan';

export interface DisplayConfig {
  threshold_label: string;
  threshold_abbrev: string;
  threshold_unit: string;
  load_label: string;
  load_unit: string;
  intensity_metric: string;
  zone_names: string[];
  trend_label: string;
}

export type UnitSystem = 'metric' | 'imperial';

export type UiLanguage = 'en' | 'zh';

/** User's preferred source for each data category plus an optional
 *  per-metric override map. Category keys (activities / recovery / fitness
 *  / plan) carry a single provider name; `threshold_sources` carries the
 *  user's chosen source per threshold metric (e.g. `cp_estimate: "stryd"`)
 *  when the auto-selected source isn't what they want. */
export interface SettingsPreferences extends Partial<Record<DataCategory, PlatformName | PlanSourceName>> {
  threshold_sources?: Partial<Record<string, string>>;
}

export interface SettingsConfig {
  display_name: string;
  unit_system: UnitSystem;
  connections: PlatformName[];
  preferences: SettingsPreferences;
  training_base: TrainingBase;
  thresholds: Record<string, number | string | null>;
  zones: Record<string, number[]>;
  goal: { race_date?: string; distance?: string; target_time_sec?: number; [key: string]: unknown };
  source_options: Record<string, unknown>;
  /** UI language preference ("en" | "zh"). `null` means auto-detect from browser. */
  language: UiLanguage | null;
}

export interface ThresholdValue {
  value: number | null;
  origin: string;
}

export interface DetectedThresholdOption {
  source: string;
  value: number;
  date: string | null;
}

export interface DetectedThreshold {
  /** Latest value across all sources (display convenience). */
  value: number;
  /** Source behind the latest value. */
  source: string;
  /** All known sources for this threshold. One entry per source,
   *  each with that source's most recent value. Powers the Settings
   *  source-selector; a single-entry list renders as read-only. */
  options: DetectedThresholdOption[];
}

export interface SettingsResponse {
  config: SettingsConfig;
  platform_capabilities: Partial<Record<PlatformName, Partial<Record<DataCategory, boolean>>>>;
  available_providers: Partial<Record<DataCategory, PlatformName[]>>;
  available_bases: TrainingBase[];
  display: DisplayConfig;
  detected_thresholds: Record<string, DetectedThreshold>;
  effective_thresholds: Record<string, ThresholdValue>;
}

export interface PlatformConnection {
  status: string;
  last_sync: string | null;
  has_credentials: boolean;
  // Scheduler retry-state surfaced for UI: when status is "error", the
  // connection is in exponential backoff and `next_retry_at` says when
  // the next attempt fires; when status is "auth_required" the user
  // must reconnect and `next_retry_at` is null. `last_error` is a short
  // tag for the failure cause (e.g. "GarminConnectConnectionError:
  // Portal login failed (non-JSON): HTTP 403"), suitable for a tooltip.
  next_retry_at?: string | null;
  consecutive_failures?: number;
  last_error?: string | null;
}

export interface ConnectionsResponse {
  connections: Partial<Record<PlatformName, PlatformConnection>>;
}

export interface StravaOAuthStartRequest {
  web_origin: string;
  return_to: string;
  client_id?: string;
  client_secret?: string;
}

export interface StravaOAuthStartResponse {
  authorize_url: string;
}

export type StravaOAuthStatus = 'connected' | 'error';

export interface StravaOAuthResult {
  status: StravaOAuthStatus;
  message: string | null;
}

export interface SyncStatus {
  status: 'idle' | 'syncing' | 'done' | 'error';
  last_sync: string | null;
  error: string | null;
  progress?: string | null;
}

export type SyncStatusResponse = Record<string, SyncStatus>;

export interface RecoveryData {
  readiness?: number;
  hrv_ms?: number;
  hrv_trend_pct?: number;
  sleep_score?: number;
  tsb: number;
}

export interface PlanData {
  workout_type?: string;
  duration_min?: number;
  distance_km?: number;
  power_min?: number;
  power_max?: number;
  description?: string;
}

export interface PlannedWorkout {
  date: string;
  workout_type: string;
  duration_min?: number;
  distance_km?: number;
  power_min?: number;
  power_max?: number;
  description?: string;
}

export interface PlanResponse {
  workouts: PlannedWorkout[];
  /** Server emits the key on every response with `null` when CP is unknown. */
  cp_current: number | null;
  /** Stryd push history. Used to be served by GET /api/plan/stryd-status. */
  stryd_status: StrydPushStatus;
}

export type StrydPushResult =
  | { date: string; status: 'success'; workout_id: string }
  | { date: string; status: 'error'; error: string };

export interface StrydPushStatusEntry {
  workout_id: string;
  pushed_at: string;
  status: 'pushed';
}

export type StrydPushStatus = Record<string, StrydPushStatusEntry>;

export interface TrainingSignal {
  recommendation: 'follow_plan' | 'easy' | 'modify' | 'reduce_intensity' | 'rest';
  reason: string;
  alternatives: string[];
  recovery: RecoveryData;
  plan: PlanData;
}

export interface TsbSparkline {
  dates: string[];
  values: number[];
  /** Projected future dates (from training plan). */
  projected_dates?: string[];
  projected_values?: number[];
}

export interface RecoveryTheoryMeta {
  id: string;
  name: string;
  simple_description: string;
  params: Record<string, number>;
}

export interface HrvAnalysis {
  today_ms: number | null;
  today_ln: number;
  baseline_mean_ln: number;
  baseline_sd_ln: number;
  threshold_ln: number;
  swc_upper_ln: number;
  rolling_mean_ln: number;
  rolling_cv: number;
  trend: 'stable' | 'improving' | 'declining';
}

export type RecoveryStatus = 'fresh' | 'normal' | 'fatigued' | 'insufficient_data';

export interface RecoveryAnalysis {
  status: RecoveryStatus;
  hrv: HrvAnalysis | null;
  sleep_score: number | null;
  /** Platform-emitted readiness score (Oura, Garmin Body Battery, …)
   *  on a 0–100 scale. Distinct from sleep_score — Oura users get
   *  both side-by-side; sources that don't surface readiness leave
   *  this null. Informational, never combined into a composite. */
  readiness_score: number | null;
  resting_hr: number | null;
  rhr_trend: 'stable' | 'elevated' | 'low' | null;
  /** ISO date of the most recent recovery reading, or null when no data exists. */
  latest_date: string | null;
  /** True when latest_date is before today — UI should label the data instead of rendering it as "today's". */
  is_stale: boolean;
}

export interface LastActivity {
  date: string;
  activity_type: string;
  distance_km: number | null;
  duration_sec: number | null;
  avg_power: number | null;
  avg_pace_min_km: string | null;
  rss: number | null;
}

export interface WeekLoad {
  week_label: string;
  actual: number;
  planned: number | null;
}

export interface UpcomingWorkout {
  date: string;
  workout_type: string;
  duration_min: number | null;
}

export interface TodayResponse {
  signal: TrainingSignal;
  tsb_sparkline: TsbSparkline;
  warnings: string[];
  recovery_theory?: RecoveryTheoryMeta;
  recovery_analysis?: RecoveryAnalysis;
  last_activity?: LastActivity;
  week_load?: WeekLoad;
  upcoming?: UpcomingWorkout[];
  data_meta?: DataMeta;
  science_notes?: ScienceNotes;
}

export interface ZoneDistribution {
  name: string;
  actual_pct: number;
  target_pct: number | null;
}

export interface ZoneRange {
  name: string;
  lower: number;
  upper: number | null;
  unit: string;
}

export interface DiagnosisFinding {
  type: 'positive' | 'warning' | 'neutral';
  message: string;
}

export interface DiagnosisData {
  lookback_weeks: number;
  interval_power: {
    max: number | null;
    avg_work: number | null;
    supra_cp_sessions: number;
    total_quality_sessions: number;
  };
  volume: {
    weekly_avg_km: number;
    trend: string;
  };
  distribution: ZoneDistribution[];
  zone_ranges: ZoneRange[];
  theory_name: string;
  consistency: {
    weeks_with_gaps: number;
    longest_gap_days: number;
    total_sessions: number;
  };
  diagnosis: DiagnosisFinding[];
  suggestions: string[];
}

export interface TimeSeriesData {
  dates: string[];
  ctl: number[];
  atl: number[];
  tsb: number[];
  /** Projected future dates (from training plan). */
  projected_dates?: string[];
  projected_ctl?: number[];
  projected_atl?: number[];
  projected_tsb?: number[];
}

export interface CpTrendChart {
  dates: string[];
  values: number[];
}

export interface WeeklyReview {
  weeks: string[];
  actual_load: number[];
  planned_load: number[];
  planned_estimated?: boolean;
}

export interface WorkoutFlag {
  type: 'good' | 'bad';
  date: string;
  description: string;
}

export interface DataMeta {
  activity_count: number;
  data_days: number;
  cp_points: number;
  has_recovery: boolean;
  pmc_sufficient: boolean;
  cp_trend_sufficient: boolean;
}

export interface ScienceNoteInfo {
  name: string;
  description: string;
  citations: { label: string; url: string }[];
}

export type ScienceNotes = Record<string, ScienceNoteInfo>;

export interface SleepPerfData {
  pairs: [number, number][];
  metric_label: string;
  metric_unit: string;
}

export interface TrainingResponse {
  diagnosis: DiagnosisData;
  fitness_fatigue: TimeSeriesData;
  cp_trend: CpTrendChart;
  weekly_review: WeeklyReview;
  workout_flags: WorkoutFlag[];
  sleep_perf: SleepPerfData;
  training_base?: TrainingBase;
  display?: DisplayConfig;
  data_meta?: DataMeta;
  science_notes?: ScienceNotes;
}

export interface Milestone {
  cp: number;
  marathon: string;
  reached: boolean;
}

export interface RaceCountdown {
  mode: 'race_date' | 'cp_milestone' | 'continuous' | 'none';
  race_date?: string;
  days_left?: number;
  predicted_time_sec?: number | null;
  target_time_sec?: number | null;
  /** Current threshold in base-native units (W / bpm / sec·km⁻¹).
   *  Pair with `display.threshold_unit` to format. */
  current_cp?: number | null;
  /** Target threshold in the same base-native units as `current_cp`.
   *  Always null for HR-base users (LTHR is not a trainable race target). */
  target_cp?: number | null;
  cp_gap_watts?: number | null;
  status: string;
  milestones?: Milestone[];
  estimated_months?: number | null;
  distance?: string;
  distance_label?: string;
  /** Which prediction MODEL actually produced `predicted_time_sec`. */
  prediction_method?: 'critical_power' | 'riegel' | 'none';
  /** Display name of the science theory, if the active set has one. */
  prediction_theory?: string | null;
  cp_trend_summary?: {
    direction: string;
    slope_per_month: number;
  };
  reality_check: {
    assessment: string;
    severity: string;
    trend_note?: string;
    cp_gap_watts?: number | null;
    cp_gap_pct?: number | null;
    current_cp?: number | null;
    needed_cp?: number | null;
    realistic_targets?: {
      comfortable: number;
      stretch: number;
    };
  };
}

export interface CpTrendData {
  current: number | null;
  avg_recent?: number;
  direction: string;
  slope_per_month?: number;
  months_flat?: number;
}

export interface GoalResponse {
  race_countdown: RaceCountdown;
  cp_trend: CpTrendChart;
  cp_trend_data: CpTrendData;
  /** Current threshold in base-native units (W / bpm / sec·km⁻¹).
   *  Name kept as `latest_cp` for backwards compatibility — pair with
   *  `display.threshold_unit` to format. Do NOT feed directly into any
   *  power formula: for that, use the backend-computed watts path. */
  latest_cp: number | null;
  training_base?: TrainingBase;
  display?: DisplayConfig;
  data_meta?: DataMeta;
  science_notes?: ScienceNotes;
}

export interface SplitData {
  split_num: number;
  distance_km: number | null;
  duration_sec: number | null;
  avg_power: number | null;
  avg_hr: number | null;
  avg_pace_min_km: string | null;
}

export interface Activity {
  activity_id: string;
  date: string;
  activity_type: string;
  distance_km: number | null;
  duration_sec: number | null;
  avg_power: number | null;
  avg_hr: number | null;
  avg_pace_min_km: string | null;
  elevation_gain_m: number | null;
  rss: number | null;
  cp_estimate: number | null;
  splits: SplitData[];
}

export interface AiInsightFinding {
  type: 'positive' | 'warning' | 'neutral';
  text: string;
}

export interface AiInsightTranslation {
  headline: string;
  summary: string;
  findings: AiInsightFinding[];
  recommendations: string[];
}

export interface AiInsight {
  headline: string;
  summary: string;
  findings: AiInsightFinding[];
  recommendations: string[];
  meta: Record<string, unknown>;
  generated_at: string | null;
  // Issue #103: optional bilingual payload. The backend writes
  // ``translations.zh`` for LLM-generated rows; the frontend prefers the
  // current locale's block and falls back to the top-level English fields.
  translations?: Partial<Record<'zh' | 'en', AiInsightTranslation>>;
}

export type AiInsightsResponse = {
  insights: Partial<Record<string, AiInsight>>;
};

export interface HistoryResponse {
  activities: Activity[];
  total: number;
  limit: number;
  offset: number;
}

export interface SystemAnnouncement {
  id: number;
  title: string;
  body: string;
  type: 'info' | 'warning' | 'success';
  is_active: boolean;
  link_text: string | null;
  link_url: string | null;
  created_at: string;
  updated_at: string;
}
