// AUTO-SYNCED from web/src/types/api.ts by miniapp/scripts/sync-types.cjs.
// Edits here will be overwritten — change web/src/types/api.ts instead.

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
  tsb: number | null;
}

export interface PlanData {
  workout_type?: string;
  duration_min?: number;
  distance_km?: number;
  power_min?: number;
  power_max?: number;
  description?: string;
}

/**
 * Per-row Stryd sync state, derived server-side for AI-source rows by
 * joining against (a) Praxys's push log and (b) Stryd-imported plan
 * rows on the same date. Stryd-source rows omit this field — they live
 * natively on Stryd, so the AI-vs-Stryd sync question doesn't apply.
 *
 * - `synced`     — Stryd has a workout on this date and its id matches
 *                  the one we logged on push (a re-push is a no-op).
 * - `mismatch`   — Stryd has a workout on this date but its id is
 *                  unknown to us (user-edited on Stryd, or never pushed).
 *                  UI confirms before overwriting.
 * - `not_synced` — No Stryd workout on this date.
 */
export type PlanSyncState = 'synced' | 'mismatch' | 'not_synced';

/** Origin of a planned workout: AI/Praxys-authored or imported from Stryd. */
export type PlanWorkoutSource = 'ai' | 'stryd';

export interface PlannedWorkout {
  date: string;
  /** Absolute UTC instant of workout start; bucket the day in viewer tz. */
  start_time?: string | null;
  workout_type: string;
  duration_min?: number;
  distance_km?: number;
  power_min?: number;
  power_max?: number;
  description?: string;
  /** Authoring system. `'ai'` rows are Praxys-authored and may be pushed
   *  to Stryd; `'stryd'` rows were imported from Stryd directly. */
  source: PlanWorkoutSource;
  /** Present only on AI-source rows. Drives the per-row sync icon. */
  sync_state?: PlanSyncState;
}

export interface PlanResponse {
  workouts: PlannedWorkout[];
  /** Stryd push history. Used to be served by GET /api/plan/stryd-status. */
  stryd_status: StrydPushStatus;
  /** Platform AI plan rows get pushed to. `null` when the user has no
   *  push target connected — UI hides sync chrome in that case. */
  sync_target: 'stryd' | null;
  /** Server-resolved query window — clients echo this back when paging. */
  window: { start: string; end: string };
}

export type StrydPushResult =
  | { date: string; status: 'success'; workout_id: string }
  | { date: string; status: 'error'; error: string };

export interface StrydPushStatusEntry {
  workout_id: string;
  pushed_at?: string;
  status?: 'pushed';
}

export type StrydPushStatus = Record<string, StrydPushStatusEntry>;

export interface TrainingSignalMessageCode {
  code: string;
  args: Record<string, string | number>;
}

export interface TrainingSignal {
  recommendation: 'follow_plan' | 'unscheduled' | 'easy' | 'modify' | 'reduce_intensity' | 'rest';
  reason: string;
  /** Stable semantic key for client-side localization. */
  reason_code: string;
  reason_args: Record<string, string | number>;
  alternatives: string[];
  /** Stable semantic alternatives aligned with alternatives. */
  alternative_codes: TrainingSignalMessageCode[];
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
  /** True when latest_date is more than one day behind the server date. */
  is_stale: boolean;
  /** ISO date of the latest available HRV observation. */
  hrv_latest_date: string | null;
  /** True when HRV is too old to drive a same-day recommendation. */
  hrv_is_stale: boolean;
  /** ISO date of the latest available sleep-score observation. */
  sleep_latest_date: string | null;
  /** True when sleep is display-only and excluded from same-day guidance. */
  sleep_is_stale: boolean;
  /** ISO date of the latest available readiness observation. */
  readiness_latest_date: string | null;
  /** True when readiness is display-only and excluded from AI context. */
  readiness_is_stale: boolean;
  /** ISO date of the latest available resting-heart-rate observation. */
  rhr_latest_date: string | null;
  /** True when RHR is display-only and excluded from same-day guidance. */
  rhr_is_stale: boolean;
  /** Why HRV could not produce a current classification, or null when classified. */
  classification_reason: 'missing_hrv' | 'insufficient_history' | 'zero_variance' | 'stale_hrv' | null;
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
  /** Absolute UTC instant of workout start; bucket the day in viewer tz. */
  start_time?: string | null;
  workout_type: string;
  duration_min: number | null;
  description?: string | null;
}

export interface TodayResponse {
  /** ISO `YYYY-MM-DD` — server-local calendar date the response was
   *  computed for. Clients should render the eyebrow against this rather
   *  than `new Date()` so a traveler whose device crossed midnight before
   *  sync caught up doesn't see "today" assert a date the server hasn't
   *  reached yet (and vice versa). Pair with
   *  `recovery_analysis.is_stale` / `latest_date` to label the actual
   *  reading date when sync lags. */
  as_of_date: string;
  /** ISO datetime of the newest recovery or activity measurement, with
   *  date-only rows anchored at noon UTC. Sync attempts and AI generation
   *  never advance it. `null` when no source data exists yet. */
  data_as_of: string | null;
  /** Opaque Today cache/source version retained for response compatibility. */
  coach_snapshot: string | null;
  signal: TrainingSignal;
  tsb_sparkline: TsbSparkline;
  warnings: string[];
  training_base: TrainingBase;
  display: DisplayConfig;
  recovery_theory: RecoveryTheoryMeta | null;
  recovery_analysis: RecoveryAnalysis | null;
  last_activity: LastActivity | null;
  week_load: WeekLoad | null;
  upcoming: UpcomingWorkout[];
  data_meta: DataMeta;
  science_notes: ScienceNotes;
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
    supra_cp_sessions: number | null;
    total_quality_sessions: number | null;
    data_available: boolean;
    evidence_complete: boolean;
    activities_with_intensity_data: number;
    activities_expected: number;
  };
  volume: {
    weekly_avg_km: number;
    trend: string;
  };
  distribution: ZoneDistribution[];
  zone_ranges: ZoneRange[];
  theory_name: string;
  data_meta: {
    distribution_resolution: 'samples' | 'splits' | 'mixed' | 'activity_averages' | 'unavailable';
    distribution_complete: boolean;
    distribution_coverage_pct: number;
  };
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
  actual_estimated: boolean;
  planned_estimated: boolean;
  week_actual_estimated: boolean[];
  week_planned_estimated: boolean[];
  week_complete: boolean[];
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
  load_time_constant_days: number;
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

export interface TrainingSummary {
  current_tsb: number | null;
  distribution_match_pct: number | null;
  load_compliance_pct: number | null;
}

export interface TrainingResponse {
  diagnosis: DiagnosisData;
  fitness_fatigue: TimeSeriesData;
  cp_trend: CpTrendChart;
  weekly_review: WeeklyReview;
  summary: TrainingSummary;
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

export type InsightFeedbackVote = 'up' | 'down';

export interface AiInsightFeedbackState {
  dataset_hash: string;
  vote: InsightFeedbackVote;
  submitted_at: string;
}

export interface AiInsightMeta extends Record<string, unknown> {
  dataset_hash?: string;
  model?: string;
  pillars?: Record<string, string>;
  feedback?: AiInsightFeedbackState;
}

export interface InsightFeedbackRequest {
  vote: InsightFeedbackVote;
  dataset_hash: string;
  comment?: string | null;
}

export interface InsightFeedbackResponse {
  accepted: boolean;
  duplicate: boolean;
  feedback: AiInsightFeedbackState;
}

export type ProductEventName =
  | 'app_opened'
  | 'today_brief_rendered'
  | 'today_reasoning_opened'
  | 'today_feedback_shown'
  | 'today_feedback_submitted';

export type TodayFeedbackResponse =
  | 'changed_plan'
  | 'confirmed_plan'
  | 'not_helpful'
  | 'not_training';

export type NonDecisionProductEventName = Exclude<
  ProductEventName,
  'today_feedback_submitted'
>;

export type ProductEventRequest =
  | {
      event_name: NonDecisionProductEventName;
      surface: 'web' | 'miniapp';
      app_version: string;
      response?: null;
    }
  | {
      event_name: 'today_feedback_submitted';
      surface: 'web' | 'miniapp';
      app_version: string;
      response: TodayFeedbackResponse;
    };

export interface ProductEventResponse {
  accepted: boolean;
  duplicate: boolean;
}
export interface AiInsight {
  headline: string;
  summary: string;
  findings: AiInsightFinding[];
  recommendations: string[];
  meta: AiInsightMeta;
  generated_at: string | null;
  feedback_allowed: boolean;
  // Issue #103: optional bilingual payload. The backend writes
  // ``translations.zh`` for LLM-generated rows; the frontend prefers the
  // current locale's block and falls back to the top-level English fields.
  translations?: Partial<Record<'zh' | 'en', AiInsightTranslation>>;
}

export interface AiInsightResponse {
  insight: AiInsight | null;
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

/** Per-locale override for an announcement's translatable text (Issue #355). */
export interface AnnouncementTranslation {
  title?: string;
  body?: string;
  link_text?: string;
}

export interface SystemAnnouncement {
  id: number;
  title: string;
  body: string;
  type: 'info' | 'warning' | 'success';
  is_active: boolean;
  link_text: string | null;
  link_url: string | null;
  // Issue #355: optional per-locale overrides. The backend keeps the English
  // base at the top level; the frontend prefers translations[locale] and falls
  // back to the top-level fields (mirrors the AiInsight #103 contract).
  translations?: Partial<Record<'zh' | 'en', AnnouncementTranslation>>;
  created_at: string | null;
  updated_at: string | null;
}

// --- Service status page (public) ---

/** Per-component health, ascending severity. */
export type ComponentStatus =
  | 'operational'
  | 'degraded_performance'
  | 'partial_outage'
  | 'major_outage';

/** Overall banner state (worst of component + active-incident severities). */
export type OverallStatus =
  | 'operational'
  | 'degraded'
  | 'partial_outage'
  | 'major_outage';

export type IncidentStatus = 'investigating' | 'identified' | 'monitoring' | 'resolved';

export type IncidentImpact = 'minor' | 'major' | 'critical';

export interface StatusComponent {
  key: string;
  name: string;
  status: ComponentStatus;
}

export interface IncidentUpdate {
  id: number;
  status: IncidentStatus;
  body: string;
  created_at: string;
}

export interface ServiceIncident {
  id: number;
  title: string;
  status: IncidentStatus;
  impact: IncidentImpact;
  started_at: string;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
  updates: IncidentUpdate[];
}

/** Response of GET /api/status (public). */
export interface ServiceStatus {
  overall: OverallStatus;
  components: StatusComponent[];
  incidents: ServiceIncident[];
  updated_at: string;
}

// --- Feedback (bug report / feature request / general) ---

export type FeedbackKind = 'bug' | 'feature' | 'other';

export type FeedbackStatus = 'new' | 'triaged' | 'needs_review' | 'issue_created' | 'resolved' | 'failed' | 'rejected';

/** LLM-suggested triage priority. Null on a ticket triaged without an LLM
 * (the rule-based fallback doesn't guess) or not yet triaged. */
export type FeedbackPriority = 'low' | 'medium' | 'high' | 'critical';

/** Client → POST /api/feedback. `context` is auto-captured diagnostics
 * (page, app version, user agent, viewport, locale); the server scrubs it to
 * an allowlist before anything is published externally. */
export interface FeedbackRequest {
  kind: FeedbackKind;
  message: string;
  context?: Record<string, string | number | boolean>;
  locale?: string;
  /** Optional screenshots (issue #337): base64 data-URLs (`data:image/png;base64,…`).
   * Max 3, each ≤5 MB (png/jpg/webp). Stored privately; a vision model produces a
   * scrubbed description and sensitivity verdict — the raw image never reaches a
   * public issue. */
  images?: string[];
}

export interface FeedbackResponse {
  ok: boolean;
  id: number;
  status: string;
}

/** Admin view row — GET /api/admin/feedback. Includes the raw `message`
 * (admin-only) alongside the scrubbed `ai_*` output that was published. */
export interface AdminFeedbackItem {
  id: number;
  user_id: string | null;
  kind: FeedbackKind;
  message: string;
  context: Record<string, unknown>;
  locale: string | null;
  status: FeedbackStatus;
  ai_title: string | null;
  ai_body: string | null;
  ai_labels: string[];
  /** LLM-suggested triage priority, or null (rule-based / not yet triaged). */
  priority: FeedbackPriority | null;
  github_issue_number: number | null;
  github_issue_url: string | null;
  error: string | null;
  /** Number of attached screenshots. Each is fetched (admin-only) from
   * `GET /api/admin/feedback/{id}/image/{index}` for index in `0..image_count-1`. */
  image_count: number;
  /** Vision-derived, PII-scrubbed description of the screenshot(s), or null. */
  image_description: string | null;
  /** Vision sensitivity verdict; null when not analysed (no vision model). */
  image_sensitive: boolean | null;
  created_at: string | null;
  updated_at: string | null;
}
/** GET /api/admin/feedback/summary — counts for the admin notification badge. */
export interface AdminFeedbackSummary {
  needs_review: number;
  failed: number;
  new: number;
  /** needs_review + failed — the rows an admin should act on. */
  actionable: number;
  total: number;
}

/** POST /api/admin/feedback/sync — reconciles ticket status with the linked
 * GitHub issues (closed → resolved, reopened → issue_created). */
export interface AdminFeedbackSyncResult {
  /** False when GitHub isn't configured — the sync was a no-op. */
  configured: boolean;
  /** How many linked issues were successfully read from GitHub. */
  checked: number;
  /** How many ticket statuses changed as a result. */
  updated: number;
}

// --- Admin operations console ---

export type AdminOpsWindow = '24h' | '7d' | '28d';
export type AdminOpsFreshness = 'fresh' | 'stale' | 'unavailable';
export type AdminOpsSource = 'praxys_database' | 'live_probe' | 'azure_monitor';
export type AdminOpsReason = 'section_refresh_failed' | 'azure_telemetry_not_connected';
export type AdminOpsSectionWindow = 'live' | 'rolling_1d_7d_30d' | AdminOpsWindow;

export interface AdminOpsSectionMeta {
  source: AdminOpsSource;
  window: AdminOpsSectionWindow;
  freshness: AdminOpsFreshness;
  as_of: string | null;
  reason: AdminOpsReason | null;
}

export interface AdminOpsIncidentCounts {
  total: number;
  minor: number;
  major: number;
  critical: number;
}

export interface AdminOpsFeedbackCounts {
  needs_review: number;
  failed: number;
  new: number;
  actionable: number;
  critical: number;
  high: number;
  total: number;
}

export interface AdminOpsActiveIncident {
  id: number;
  title: string;
  status: IncidentStatus;
  impact: IncidentImpact;
  started_at: string | null;
  updated_at: string | null;
}

export interface AdminOpsAttentionData {
  incident_counts: AdminOpsIncidentCounts;
  active_incidents: AdminOpsActiveIncident[];
  feedback: AdminOpsFeedbackCounts;
}

export interface AdminOpsAttentionSection extends AdminOpsSectionMeta {
  data: AdminOpsAttentionData | null;
}

export interface AdminOpsServiceHealthData {
  overall: OverallStatus;
  components: StatusComponent[];
}

export interface AdminOpsServiceHealthSection extends AdminOpsSectionMeta {
  data: AdminOpsServiceHealthData | null;
}

export interface AdminOpsProductValueData {
  registered_users: number;
  dau: number;
  wau: number;
  mau: number;
  directional: boolean;
}

export interface AdminOpsProductValueSection extends AdminOpsSectionMeta {
  data: AdminOpsProductValueData | null;
}

export interface AdminOpsUnavailableSection extends AdminOpsSectionMeta {
  data: null;
}

export interface AdminOpsLinks {
  users: string;
  feedback: string;
  incidents: string;
  communications: string;
  public_status: string;
  monitoring_docs: string;
  telemetry_trust_issue: string;
}

/** GET /api/admin/ops/summary. Aggregate-only and admin-only. */
export interface AdminOpsSummary {
  generated_at: string;
  window: AdminOpsWindow;
  attention: AdminOpsAttentionSection;
  service_health: AdminOpsServiceHealthSection;
  product_value: AdminOpsProductValueSection;
  azure_alerts: AdminOpsUnavailableSection;
  platform_health: AdminOpsUnavailableSection;
  links: AdminOpsLinks;
}
/** GET /api/public/config — unauthenticated; drives the login page's signup path. */
export interface PublicConfig {
  /** Effective self-registration state (admin flag AND under the seat cap). */
  registration_open: boolean;
}

/** Admin-only user row from GET /api/admin/users. */
export interface AdminUserInfo {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_demo: boolean;
  demo_of: string | null;
  demo_of_email: string | null;
  created_at: string | null;
}

export interface AdminUsersResponse {
  users: AdminUserInfo[];
}

/** Admin-only invitation row from GET /api/admin/invitations. */
export interface AdminInvitationInfo {
  id: number;
  code: string;
  note: string | null;
  is_active: boolean;
  created_at: string | null;
  used_by: string | null;
  used_at: string | null;
}

export interface AdminInvitationsResponse {
  invitations: AdminInvitationInfo[];
}

export interface AdminInvitationCreateResponse {
  code: string;
  note: string;
}
/** Registration gate + seat cap (admin only). */
export interface RegistrationStatus {
  registration_open: boolean;
  flag_enabled: boolean;
  max_users: number;
  /** Actual registered non-demo accounts. */
  registered_users: number;
  /** Active, unused, unexpired invitation codes (each reserves a seat). */
  outstanding_invitations: number;
  /** registered_users + outstanding_invitations — what the cap measures. */
  committed_seats: number;
  /** max(max_users - committed_seats, 0). */
  remaining: number;
  cap_reached: boolean;
}

/** DAU/WAU readiness gauge (admin only). */
export interface ActivityCounts {
  dau: number;
  wau: number;
  mau: number;
  total_users: number;
}

/** GET/PATCH /api/admin/config. */
export interface AdminConfig {
  registration: RegistrationStatus;
  activity: ActivityCounts;
  email_configured: boolean;
}

/** A row from GET /api/admin/waitlist. */
export interface WaitlistSignupItem {
  id: number;
  email: string;
  note: string | null;
  locale: string | null;
  created_at: string | null;
  invited_at: string | null;
  invitation_id: number | null;
  invitation_code: string | null;
  /** True once an account exists for this email (invited or open path). */
  registered: boolean;
}

export interface AdminWaitlistResponse {
  signups: WaitlistSignupItem[];
}

/** POST /api/admin/waitlist/{id}/invite result. */
export interface WaitlistInviteResult {
  sent: boolean;
  email_configured: boolean;
  code: string;
  email: string;
  invite_url: string;
  expires_at: string | null;
}
