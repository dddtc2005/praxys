// API response types

export type TrainingBase = 'power' | 'hr' | 'pace';
export type PlatformName = 'garmin' | 'stryd' | 'oura' | 'coros';
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

export interface SettingsConfig {
  connections: PlatformName[];
  preferences: Partial<Record<DataCategory, PlatformName>>;
  training_base: TrainingBase;
  thresholds: Record<string, number | string | null>;
  zones: Record<string, number[]>;
  goal: Record<string, string | number>;
  source_options: Record<string, string>;
}

export interface ThresholdValue {
  value: number | null;
  origin: string;
}

export interface DetectedThreshold {
  value: number;
  source: string;
}

export interface SettingsResponse {
  config: SettingsConfig;
  platform_capabilities: Record<PlatformName, Record<DataCategory, boolean>>;
  available_providers: Record<DataCategory, PlatformName[]>;
  available_bases: TrainingBase[];
  display: DisplayConfig;
  detected_thresholds: Record<string, DetectedThreshold>;
  effective_thresholds: Record<string, ThresholdValue>;
}

export interface SyncStatus {
  status: 'idle' | 'syncing' | 'done' | 'error';
  last_sync: string | null;
  error: string | null;
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
  cp_current?: number;
}

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
}

export interface TodayResponse {
  signal: TrainingSignal;
  tsb_sparkline: TsbSparkline;
  warnings: string[];
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
  distribution: {
    supra_cp: number;
    threshold: number;
    tempo: number;
    easy: number;
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
}

export interface CpTrendChart {
  dates: string[];
  values: number[];
}

export interface WeeklyReview {
  weeks: string[];
  actual_rss: number[];
  planned_rss: number[];
}

export interface WorkoutFlag {
  type: 'good' | 'bad';
  date: string;
  description: string;
}

export interface TrainingResponse {
  diagnosis: DiagnosisData;
  fitness_fatigue: TimeSeriesData;
  cp_trend: CpTrendChart;
  weekly_review: WeeklyReview;
  workout_flags: WorkoutFlag[];
  sleep_perf: [number, number][];
  training_base?: TrainingBase;
  display?: DisplayConfig;
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
  predicted_time_sec?: number;
  target_time_sec?: number;
  current_cp?: number;
  target_cp?: number;
  cp_gap_watts?: number;
  status: string;
  milestones?: Milestone[];
  estimated_months?: number | null;
  distance?: string;
  distance_label?: string;
  cp_trend_summary?: {
    direction: string;
    slope_per_month: number;
  };
  reality_check: {
    assessment: string;
    severity: string;
    trend_note?: string;
    cp_gap_watts?: number;
    cp_gap_pct?: number;
    current_cp?: number;
    needed_cp?: number;
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
  latest_cp: number | null;
  training_base?: TrainingBase;
  display?: DisplayConfig;
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

export interface HistoryResponse {
  activities: Activity[];
  total: number;
  limit: number;
  offset: number;
}
