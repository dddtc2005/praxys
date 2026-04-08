import { useState } from 'react';
import { useApi } from '@/hooks/useApi';
import { useSettings } from '@/contexts/SettingsContext';
import type { GoalResponse } from '@/types/api';
import MilestoneTracker from '@/components/MilestoneTracker';
import CpTrendChart from '@/components/charts/CpTrendChart';
import ScienceNote from '@/components/ScienceNote';

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function formatPace(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = Math.round(totalSec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatThreshold(value: number, unit: string): string {
  if (unit === '/km') return formatPace(value);
  return String(Math.round(value));
}

function parseTimeToSeconds(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(':').map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 3600 + parts[1] * 60;
  if (parts.length === 1 && parts[0] > 0) return parts[0];
  return null;
}

type Severity = 'on_track' | 'close' | 'behind' | 'unlikely';

function severityColor(severity: string): string {
  switch (severity as Severity) {
    case 'on_track':
      return 'text-primary';
    case 'close':
      return 'text-accent-amber';
    case 'behind':
    case 'unlikely':
      return 'text-destructive';
    default:
      return 'text-muted-foreground';
  }
}

function severityBgColor(severity: string): string {
  switch (severity as Severity) {
    case 'on_track':
      return 'bg-primary/15 text-primary';
    case 'close':
      return 'bg-accent-amber/15 text-accent-amber';
    case 'behind':
    case 'unlikely':
      return 'bg-destructive/15 text-destructive';
    default:
      return 'bg-muted text-muted-foreground';
  }
}

function StatusBadge({ status, severity }: { status: string; severity: string }) {
  return (
    <span
      className={`inline-block rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider ${severityBgColor(severity)}`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function trendDirectionLabel(direction: string): string {
  if (direction === 'rising') return 'Rising';
  if (direction === 'falling') return 'Falling';
  return 'Flat';
}

// Science note for methodology transparency
// --- Constants ---

const DISTANCES = [
  { value: '5k', label: '5K', placeholder: 'e.g. 20:00' },
  { value: '10k', label: '10K', placeholder: 'e.g. 42:00' },
  { value: 'half', label: 'Half', placeholder: 'e.g. 1:30:00' },
  { value: 'marathon', label: 'Marathon', placeholder: 'e.g. 3:00:00' },
  { value: '50k', label: '50K', placeholder: 'e.g. 4:30:00' },
  { value: '50mi', label: '50 Mi', placeholder: 'e.g. 8:00:00' },
  { value: '100k', label: '100K', placeholder: 'e.g. 12:00:00' },
  { value: '100mi', label: '100 Mi', placeholder: 'e.g. 24:00:00' },
];

const SCIENCE_POWER = 'Predicted using Stryd race power model (5K at 103.8% CP, marathon at 89.9% CP).';
const SCIENCE_POWER_URL = 'https://help.stryd.com/en/articles/6879547-race-power-calculator';
const SCIENCE_PACE = 'Predicted using Riegel\u2019s formula (T\u2082 = T\u2081 \u00d7 (D\u2082/D\u2081)^1.06), treating threshold pace as ~10K effort.';
const SCIENCE_PACE_URL = 'https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html';

function predictionNote(base?: string) {
  if (base === 'power') return { text: SCIENCE_POWER, url: SCIENCE_POWER_URL };
  return { text: SCIENCE_PACE, url: SCIENCE_PACE_URL };
}

// --- Goal Editor ---

type GoalType = 'race' | 'continuous';

interface GoalEditorProps {
  initialType: GoalType;
  initialRaceDate: string;
  initialDistance: string;
  initialTargetTime: number | null;
  onSave: (goal: { race_date: string; distance: string; target_time_sec: number }) => Promise<void>;
  onCancel?: () => void;
}

function GoalEditor({ initialType, initialRaceDate, initialDistance, initialTargetTime, onSave, onCancel }: GoalEditorProps) {
  const [goalType, setGoalType] = useState<GoalType>(initialType);
  const [raceDate, setRaceDate] = useState(initialRaceDate);
  const [distance, setDistance] = useState(initialDistance || 'marathon');
  const [targetTimeInput, setTargetTimeInput] = useState(
    initialTargetTime ? formatTime(initialTargetTime) : ''
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const selectedDist = DISTANCES.find((d) => d.value === distance);

  const handleSave = async () => {
    setError('');

    if (goalType === 'race' && !raceDate) {
      setError('Race date is required');
      return;
    }

    const targetTimeSec = parseTimeToSeconds(targetTimeInput);
    if (targetTimeInput.trim() && targetTimeSec === null) {
      setError('Invalid time format. Use H:MM:SS or H:MM');
      return;
    }

    setSaving(true);
    try {
      await onSave({
        race_date: goalType === 'race' ? raceDate : '',
        distance,
        target_time_sec: targetTimeSec || 0,
      });
    } catch {
      setError('Failed to save goal');
    }
    setSaving(false);
  };

  return (
    <div className="rounded-2xl bg-card p-5 sm:p-6 mb-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
        Set Your Goal
      </h3>

      {/* Goal type selection */}
      <div className="grid grid-cols-2 gap-3 mb-5">
        <button
          onClick={() => setGoalType('race')}
          className={`rounded-xl p-4 text-left transition-colors border-2 ${
            goalType === 'race'
              ? 'border-primary bg-primary/10'
              : 'border-border bg-muted hover:border-text-muted'
          }`}
        >
          <p className={`font-semibold ${goalType === 'race' ? 'text-primary' : 'text-foreground'}`}>
            Race Goal
          </p>
          <p className="text-xs text-muted-foreground mt-1">Train toward a specific race date</p>
        </button>
        <button
          onClick={() => setGoalType('continuous')}
          className={`rounded-xl p-4 text-left transition-colors border-2 ${
            goalType === 'continuous'
              ? 'border-primary bg-primary/10'
              : 'border-border bg-muted hover:border-text-muted'
          }`}
        >
          <p className={`font-semibold ${goalType === 'continuous' ? 'text-primary' : 'text-foreground'}`}>
            Continuous Improvement
          </p>
          <p className="text-xs text-muted-foreground mt-1">Build fitness over time</p>
        </button>
      </div>

      {/* Distance selection */}
      <div className="mb-5">
        <label className="block text-xs text-muted-foreground mb-2">Distance</label>
        <div className="grid grid-cols-4 gap-2">
          {DISTANCES.map((d) => (
            <button
              key={d.value}
              onClick={() => setDistance(d.value)}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                distance === d.value
                  ? 'bg-primary/15 text-primary border border-primary/30'
                  : 'bg-muted text-muted-foreground border border-border hover:text-foreground hover:border-text-muted'
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {/* Conditional fields */}
      <div className="space-y-4 mb-5">
        {goalType === 'race' && (
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Race Date</label>
            <input
              type="date"
              value={raceDate}
              onChange={(e) => setRaceDate(e.target.value)}
              className="rounded-lg bg-muted border border-border px-3 py-2 text-sm text-foreground focus:outline-none focus:border-primary w-full sm:w-auto"
            />
          </div>
        )}

        <div>
          <label className="block text-xs text-muted-foreground mb-1">
            Target Time <span className="text-muted-foreground/60">(optional)</span>
          </label>
          <input
            type="text"
            value={targetTimeInput}
            onChange={(e) => setTargetTimeInput(e.target.value)}
            placeholder={selectedDist?.placeholder ?? 'H:MM:SS'}
            className="rounded-lg bg-muted border border-border px-3 py-2 text-sm font-data text-foreground focus:outline-none focus:border-primary w-full sm:w-48"
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            {goalType === 'race'
              ? 'Leave blank to track predicted time only'
              : 'What time are you working toward? Leave blank to track trend only'}
          </p>
        </div>
      </div>

      {error && <p className="text-xs text-destructive mb-3">{error}</p>}

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg bg-primary/15 px-4 py-2 text-sm font-semibold text-primary hover:bg-primary/25 transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Goal'}
        </button>
        {onCancel && (
          <button
            onClick={onCancel}
            className="rounded-lg px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

// --- Tracking Modes ---

function RaceDateMode({ data }: { data: GoalResponse }) {
  const rc = data.race_countdown;
  const rCheck = rc.reality_check;
  const hasTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const distLabel = rc.distance_label || 'Race';
  const d = data.display;
  const unit = d?.threshold_unit || 'W';
  const abbrev = d?.threshold_abbrev || 'CP';
  const note = predictionNote(data.training_base);

  return (
    <div className="space-y-4">
      {/* Hero: Countdown */}
      <div className="rounded-2xl bg-card p-5 sm:p-6 text-center">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          {distLabel} Countdown
        </h3>
        <div className="flex flex-col items-center gap-2">
          <span className="font-data text-6xl font-bold text-foreground">
            {rc.days_left ?? '\u2014'}
          </span>
          <span className="text-sm text-muted-foreground">
            days until {rc.race_date ?? 'race day'}
          </span>
          <StatusBadge status={rc.status} severity={rCheck.severity} />
        </div>

        {/* Predicted vs Target */}
        <div className={`mt-6 grid gap-4 ${hasTarget ? 'grid-cols-2' : 'grid-cols-1'}`}>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Predicted {distLabel}</p>
            <p className="font-data text-2xl text-foreground">
              {rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '\u2014'}
            </p>
          </div>
          {hasTarget && (
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Target</p>
              <p className="font-data text-2xl text-foreground">
                {formatTime(rc.target_time_sec!)}
              </p>
            </div>
          )}
        </div>
        <ScienceNote text={note.text} sourceUrl={note.url} sourceLabel="Source" />
      </div>

      {/* Reality Check — only when we have a target and meaningful assessment */}
      {hasTarget && rCheck.severity !== 'unknown' && (
        <div className="rounded-2xl bg-card p-5 sm:p-6 space-y-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Reality Check
          </h3>

          <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
            {rCheck.assessment}
          </p>

          {rCheck.current_cp != null && rCheck.needed_cp != null && (
            <div className="flex items-center gap-4 rounded-lg bg-muted px-4 py-3">
              <div className="text-center">
                <p className="text-xs text-muted-foreground">Current {abbrev}</p>
                <p className="font-data text-lg text-foreground">{formatThreshold(rCheck.current_cp, unit)}{unit}</p>
              </div>
              <div className="text-muted-foreground">&rarr;</div>
              <div className="text-center">
                <p className="text-xs text-muted-foreground">Needed {abbrev}</p>
                <p className="font-data text-lg text-foreground">{formatThreshold(rCheck.needed_cp, unit)}{unit}</p>
              </div>
              {rCheck.cp_gap_watts != null && (
                <div className="ml-auto text-center">
                  <p className="text-xs text-muted-foreground">Gap</p>
                  <p className={`font-data text-lg font-semibold ${severityColor(rCheck.severity)}`}>
                    {rCheck.cp_gap_watts > 0 ? '+' : ''}
                    {unit === '/km' ? formatPace(Math.abs(rCheck.cp_gap_watts)) : rCheck.cp_gap_watts}{unit}
                  </p>
                </div>
              )}
            </div>
          )}

          {rCheck.trend_note && (
            <p className="text-sm text-muted-foreground">{rCheck.trend_note}</p>
          )}

          {rCheck.realistic_targets &&
            (rCheck.severity === 'behind' || rCheck.severity === 'unlikely') && (
              <div className="rounded-lg bg-muted px-4 py-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  Realistic Alternative Targets
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Comfortable</p>
                    <p className="font-data text-lg text-primary">
                      {formatTime(rCheck.realistic_targets.comfortable)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Stretch</p>
                    <p className="font-data text-lg text-accent-amber">
                      {formatTime(rCheck.realistic_targets.stretch)}
                    </p>
                  </div>
                </div>
              </div>
            )}
        </div>
      )}

      {/* Trend-based assessment when no target */}
      {!hasTarget && rCheck.trend_note && (
        <div className="rounded-2xl bg-card p-5 sm:p-6">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Fitness Trend
          </h3>
          <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
            {rCheck.assessment}
          </p>
          <p className="text-sm text-muted-foreground mt-2">{rCheck.trend_note}</p>
        </div>
      )}

      {/* Threshold Trend chart */}
      <CpTrendChart data={data.cp_trend} targetCp={rc.target_cp} label={d?.trend_label} unit={d?.threshold_unit} metricName={d?.threshold_abbrev} />
    </div>
  );
}

function CpMilestoneMode({ data }: { data: GoalResponse }) {
  const rc = data.race_countdown;
  const rCheck = rc.reality_check;
  const currentCp = data.latest_cp;
  const targetCp = rc.target_cp ?? null;
  const distLabel = rc.distance_label || 'Race';
  const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const d = data.display;
  const unit = d?.threshold_unit || 'W';
  const isPace = unit === '/km';
  const note = predictionNote(data.training_base);

  // For pace, progress is inverted (lower = better)
  const progressPct = (() => {
    if (currentCp == null || targetCp == null || targetCp <= 0) return 0;
    if (isPace) return Math.min(100, Math.max(0, (targetCp / currentCp) * 100));
    return Math.min(100, Math.max(0, (currentCp / targetCp) * 100));
  })();

  const barColor =
    progressPct >= 90
      ? 'bg-primary'
      : progressPct >= 70
        ? 'bg-accent-amber'
        : 'bg-destructive';

  return (
    <div className="space-y-4">
      {/* Hero: Target + Progress */}
      <div className="rounded-2xl bg-card p-5 sm:p-6 text-center">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          {hasTimeTarget
            ? `Building toward ${formatTime(rc.target_time_sec!)} ${distLabel}`
            : `${distLabel} Progress`}
        </h3>

        {/* Time predictions */}
        {rc.predicted_time_sec != null && (
          <div className={`grid gap-4 mb-4 ${hasTimeTarget ? 'grid-cols-2' : 'grid-cols-1'}`}>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Predicted {distLabel}</p>
              <p className="font-data text-2xl text-foreground">{formatTime(rc.predicted_time_sec)}</p>
            </div>
            {hasTimeTarget && (
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Target</p>
                <p className="font-data text-2xl text-foreground">{formatTime(rc.target_time_sec!)}</p>
              </div>
            )}
          </div>
        )}

        {/* Threshold progress bar */}
        {targetCp != null && (
          <>
            <div className="flex items-baseline justify-center gap-2 mb-2">
              <span className="font-data text-4xl font-bold text-foreground">
                {currentCp != null ? formatThreshold(currentCp, unit) : '\u2014'}
              </span>
              <span className="text-muted-foreground text-lg">&rarr;</span>
              <span className="font-data text-2xl text-muted-foreground">{formatThreshold(targetCp, unit)}</span>
              <span className="text-sm text-muted-foreground">{unit}</span>
            </div>
            <div className="mx-auto max-w-md">
              <div className="h-4 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground mt-1 font-data">{progressPct.toFixed(0)}%</p>
            </div>
          </>
        )}

        <div className="mt-3">
          <StatusBadge status={rc.status} severity={rCheck.severity} />
        </div>
        <ScienceNote text={note.text} sourceUrl={note.url} sourceLabel="Source" />
      </div>

      {/* Milestones */}
      {rc.milestones && rc.milestones.length > 0 && (
        <div className="rounded-2xl bg-card p-5 sm:p-6">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Milestones
          </h3>
          <MilestoneTracker
            milestones={rc.milestones}
            currentCp={currentCp}
            targetCp={targetCp}
          />
        </div>
      )}

      {/* Assessment + details */}
      <div className="rounded-2xl bg-card p-5 sm:p-6 space-y-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Assessment
        </h3>
        <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
          {rCheck.assessment}
        </p>

        {rc.estimated_months != null && (
          <div className="rounded-lg bg-muted px-4 py-3">
            <p className="text-xs text-muted-foreground">Estimated time to target</p>
            <p className="font-data text-lg text-foreground">
              {rc.estimated_months.toFixed(1)} months
            </p>
          </div>
        )}

        {rCheck.trend_note && (
          <p className="text-sm text-muted-foreground">{rCheck.trend_note}</p>
        )}
      </div>

      {/* Threshold Trend chart */}
      <CpTrendChart data={data.cp_trend} targetCp={targetCp} label={d?.trend_label} unit={d?.threshold_unit} metricName={d?.threshold_abbrev} />
    </div>
  );
}

function ContinuousMode({ data }: { data: GoalResponse }) {
  const rc = data.race_countdown;
  const rCheck = rc.reality_check;
  const currentCp = data.latest_cp;
  const trend = rc.cp_trend_summary;
  const distLabel = rc.distance_label || 'Marathon';
  const d = data.display;
  const unit = d?.threshold_unit || 'W';
  const note = predictionNote(data.training_base);

  return (
    <div className="space-y-4">
      {/* Hero: Current Threshold + Predicted Time */}
      <div className="rounded-2xl bg-card p-5 sm:p-6 text-center">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Current Fitness
        </h3>
        <div className="flex flex-col items-center gap-2">
          <div className="flex items-baseline gap-2">
            <span className="font-data text-5xl font-bold text-foreground">
              {currentCp != null ? formatThreshold(currentCp, unit) : '\u2014'}
            </span>
            <span className="text-sm text-muted-foreground">{unit}</span>
          </div>
          {trend && (
            <div className="flex items-center gap-2">
              <span className={`text-sm font-semibold ${severityColor(rCheck.severity)}`}>
                {trendDirectionLabel(trend.direction)}
              </span>
              {trend.slope_per_month !== 0 && (
                <span className="text-xs text-muted-foreground font-data">
                  ({trend.slope_per_month > 0 ? '+' : ''}{unit === '/km' ? formatPace(Math.abs(trend.slope_per_month)) : trend.slope_per_month.toFixed(1)}{unit}/mo)
                </span>
              )}
            </div>
          )}
        </div>

        {/* Predicted time for configured distance */}
        {rc.predicted_time_sec != null && (
          <div className="mt-4 pt-4 border-t border-border">
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Predicted {distLabel}</p>
            <p className="font-data text-2xl text-foreground">{formatTime(rc.predicted_time_sec)}</p>
          </div>
        )}
        <ScienceNote text={note.text} sourceUrl={note.url} sourceLabel="Source" />
      </div>

      {/* Assessment */}
      {rCheck.trend_note && (
        <div className="rounded-2xl bg-card p-5 sm:p-6">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Trend
          </h3>
          <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
            {rCheck.assessment}
          </p>
          <p className="text-sm text-muted-foreground mt-2">{rCheck.trend_note}</p>
        </div>
      )}

      {/* Threshold Trend chart */}
      <CpTrendChart data={data.cp_trend} label={d?.trend_label} unit={d?.threshold_unit} metricName={d?.threshold_abbrev} />
    </div>
  );
}

// --- Main Goal Page ---

export default function Goal() {
  const [fetchKey, setFetchKey] = useState(0);
  const { data, loading, error } = useApi<GoalResponse>(`/api/goal?_=${fetchKey}`);
  const { config, updateSettings } = useSettings();
  const [isEditing, setIsEditing] = useState(false);

  const mode = data?.race_countdown.mode;

  // Derive current goal state from config
  const currentRaceDate = config?.goal?.race_date ? String(config.goal.race_date) : '';
  const currentDistance = config?.goal?.distance ? String(config.goal.distance) : 'marathon';
  const currentTargetTime = (() => {
    const v = config?.goal?.target_time_sec ?? config?.goal?.race_target_time_sec;
    return v ? Number(v) || null : null;
  })();
  const currentGoalType: GoalType = currentRaceDate ? 'race' : 'continuous';

  const handleSaveGoal = async (goal: { race_date: string; distance: string; target_time_sec: number }) => {
    await updateSettings({ goal });
    setFetchKey((k) => k + 1);
    setIsEditing(false);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Goal Tracker</h1>
        {!isEditing && data && (
          <button
            onClick={() => setIsEditing(true)}
            className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:border-text-muted transition-colors"
          >
            Change Goal
          </button>
        )}
      </div>

      {loading && <p className="text-muted-foreground">Loading...</p>}

      {error && (
        <div className="rounded-2xl bg-destructive/10 border border-destructive/30 p-4 mb-4">
          <p className="text-destructive text-sm">Failed to load goal data: {error}</p>
        </div>
      )}

      {isEditing && (
        <GoalEditor
          initialType={currentGoalType}
          initialRaceDate={currentRaceDate}
          initialDistance={currentDistance}
          initialTargetTime={currentTargetTime}
          onSave={handleSaveGoal}
          onCancel={() => setIsEditing(false)}
        />
      )}

      {data && !isEditing && (
        <>
          {mode === 'race_date' && <RaceDateMode data={data} />}
          {mode === 'cp_milestone' && <CpMilestoneMode data={data} />}
          {(mode === 'continuous' || mode === 'none') && <ContinuousMode data={data} />}
        </>
      )}
    </div>
  );
}
