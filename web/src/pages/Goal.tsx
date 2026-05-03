import { useState, type ReactNode } from 'react';
import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { useSettings } from '@/contexts/SettingsContext';
import type { GoalResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import GoalEditor from '@/components/GoalEditor';
import AiInsightsCard, { type CoachFallback } from '@/components/AiInsightsCard';
import CpTrendChart from '@/components/charts/CpTrendChart';
import DataHint from '@/components/DataHint';
import ScienceNote from '@/components/ScienceNote';
import { formatTime, formatPace } from '@/lib/format';
import { Trans, useLingui } from '@lingui/react/macro';
import { tDisplay } from '@/lib/display-labels';

function formatThreshold(value: number, unit: string): string {
  if (unit === '/km') return formatPace(value);
  return String(Math.round(value));
}

type Severity = 'on_track' | 'close' | 'behind' | 'unlikely';
type StripTone = 'amber' | 'positive' | 'destructive' | undefined;

function severityVariant(severity: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (severity as Severity) {
    case 'on_track': return 'default';
    case 'close': return 'secondary';
    case 'behind':
    case 'unlikely': return 'destructive';
    default: return 'outline';
  }
}

function severityTone(severity: string): StripTone {
  switch (severity as Severity) {
    case 'on_track': return 'positive';
    case 'close': return 'amber';
    case 'behind':
    case 'unlikely': return 'destructive';
    default: return undefined;
  }
}

function useTrendDirectionLabel() {
  const { t } = useLingui();
  return (direction: string): string => {
    if (direction === 'rising') return t`Rising`;
    if (direction === 'falling') return t`Falling`;
    return t`Flat`;
  };
}

const SCIENCE_POWER_URL = 'https://help.stryd.com/en/articles/6879547-race-power-calculator';
const SCIENCE_PACE_URL = 'https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html';
const SCIENCE_ULTRA_URL = 'https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html';
const ULTRA_DISTANCES = new Set(['50k', '50mi', '100k', '100mi']);

function usePredictionNote() {
  const { t } = useLingui();
  return (base?: string, scienceNotes?: Record<string, { name: string; description: string; citations: { label: string; url: string }[] }>) => {
    if (scienceNotes?.prediction?.description) {
      const pred = scienceNotes.prediction;
      return {
        text: pred.description,
        url: pred.citations?.[0]?.url || (base === 'power' ? SCIENCE_POWER_URL : SCIENCE_PACE_URL),
      };
    }
    if (base === 'power') {
      return {
        text: t`Predicted using Stryd race power model (5K at 103.8% CP, marathon at 89.9% CP).`,
        url: SCIENCE_POWER_URL,
      };
    }
    return {
      text: t`Predicted using Riegel's formula (T₂ = T₁ × (D₂/D₁)^1.06), treating threshold pace as ~10K effort.`,
      url: SCIENCE_PACE_URL,
    };
  };
}

function useUltraNote() {
  const { t } = useLingui();
  return () => t`Ultra distance power fractions (50K+) are estimates with limited research backing. Riegel's exponent is validated only up to marathon distance. Predictions beyond marathon carry significantly higher uncertainty due to factors like fueling, terrain, heat, and pacing strategy that dominate ultra performance but are not captured by power/pace models.`;
}

function isUltraDistance(distance?: string): boolean {
  return !!distance && ULTRA_DISTANCES.has(distance);
}

interface StripCell {
  label: ReactNode;
  value: string;
  sub?: ReactNode;
  tone?: StripTone;
}

function TrajectoryGoal({ data }: { data: GoalResponse }) {
  const { t, i18n } = useLingui();
  const predictionNote = usePredictionNote();
  const ultraNote = useUltraNote();
  const trendDirectionLabel = useTrendDirectionLabel();
  const rc = data.race_countdown;
  const rCheck = rc.reality_check;
  const currentCp = data.latest_cp;
  const targetCp = rc.target_cp ?? null;
  const distLabel = rc.distance_label ? tDisplay(rc.distance_label, i18n) : t`Race`;
  const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const d = data.display;
  const unit = d?.threshold_unit || 'W';
  const abbrev = d?.threshold_abbrev || 'CP';
  const isPace = unit === '/km';
  const attribution = data.science_notes?.prediction?.name;
  const mode = rc.mode;
  const note = predictionNote(data.training_base, data.science_notes);
  const trend = rc.cp_trend_summary;

  const gap = currentCp != null && targetCp != null ? targetCp - currentCp : null;
  const statusLabel = rc.status.replace(/_/g, ' ');

  const eyebrow: ReactNode = (() => {
    if (mode === 'race_date') {
      return (
        <>
          <Trans>Race</Trans> · {rc.race_date ?? distLabel}
          {hasTimeTarget && <> · {formatTime(rc.target_time_sec!)}</>}
        </>
      );
    }
    if (mode === 'cp_milestone') {
      return (
        <>
          <Trans>Goal</Trans> · {hasTimeTarget ? `${formatTime(rc.target_time_sec!)} ${distLabel}` : distLabel}
        </>
      );
    }
    return (
      <>
        <Trans>Tracking</Trans> · {distLabel}
      </>
    );
  })();

  const headline: ReactNode = (() => {
    if (mode === 'race_date') {
      const days = rc.days_left ?? 0;
      const predicted = rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—';
      if (hasTimeTarget) {
        return (
          <Trans>
            <strong className="goal-headline-num">{days}</strong> days to race day. Today's prediction is{' '}
            <strong className="goal-headline-num">{predicted}</strong> against a target of{' '}
            <strong className="goal-headline-num">{formatTime(rc.target_time_sec!)}</strong>.
          </Trans>
        );
      }
      return (
        <Trans>
          <strong className="goal-headline-num">{days}</strong> days to race day. Today's prediction is{' '}
          <strong className="goal-headline-num">{predicted}</strong>.
        </Trans>
      );
    }
    if (mode === 'cp_milestone') {
      // Drop the "X% of the way" phrasing — the (current/target) ratio is a
      // linear scale not anchored to any training-science model. Lead with the
      // concrete numbers (current → needed) and let the Coach receipt or the
      // estimated-months strip cell carry the verdict timing.
      const currentStr = currentCp != null ? formatThreshold(currentCp, unit) : '—';
      const targetStr = targetCp != null ? formatThreshold(targetCp, unit) : '—';
      if (hasTimeTarget) {
        return (
          <Trans>
            Building toward <strong className="goal-headline-num">{formatTime(rc.target_time_sec!)}</strong> {distLabel}.{' '}
            Current {abbrev} <strong className="goal-headline-num">{currentStr}{unit}</strong>, need{' '}
            <strong className="goal-headline-num">{targetStr}{unit}</strong>.
          </Trans>
        );
      }
      return (
        <Trans>
          Building toward {distLabel}. Current {abbrev}{' '}
          <strong className="goal-headline-num">{currentStr}{unit}</strong>, need{' '}
          <strong className="goal-headline-num">{targetStr}{unit}</strong>.
        </Trans>
      );
    }
    // continuous / none
    const predicted = rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : null;
    const dirLabel = trend ? trendDirectionLabel(trend.direction).toLowerCase() : t`flat`;
    const slopeStr = trend && trend.slope_per_month !== 0
      ? `${trend.slope_per_month > 0 ? '+' : ''}${isPace ? formatPace(Math.abs(trend.slope_per_month)) : trend.slope_per_month.toFixed(1)}${unit}/mo`
      : null;
    if (predicted && slopeStr) {
      return (
        <Trans>
          Today's <strong className="goal-headline-num">{distLabel}</strong> prediction is{' '}
          <strong className="goal-headline-num">{predicted}</strong>. {abbrev} is <strong>{dirLabel}</strong> at{' '}
          <strong className="goal-headline-num">{slopeStr}</strong>.
        </Trans>
      );
    }
    if (predicted) {
      return (
        <Trans>
          Today's <strong className="goal-headline-num">{distLabel}</strong> prediction is{' '}
          <strong className="goal-headline-num">{predicted}</strong>. {abbrev} is <strong>{dirLabel}</strong>.
        </Trans>
      );
    }
    return (
      <Trans>
        {abbrev} is <strong>{dirLabel}</strong>. Add more activities for a race-time prediction.
      </Trans>
    );
  })();

  const chart = (
    <DataHint
      sufficient={data.data_meta?.cp_trend_sufficient ?? true}
      message={t`Not enough data to show CP trend`}
      hint={t`Need at least 3 activities with power data.`}
    >
      <CpTrendChart
        data={data.cp_trend}
        targetCp={targetCp}
        label={d?.trend_label}
        unit={d?.threshold_unit}
        metricName={d?.threshold_abbrev}
      />
    </DataHint>
  );

  const statCells: StripCell[] = (() => {
    const cells: StripCell[] = [];
    if (mode === 'race_date') {
      cells.push({ label: t`Days left`, value: rc.days_left != null ? String(rc.days_left) : '—', sub: t`days` });
      cells.push({
        label: t`Predicted`,
        value: rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—',
        sub: distLabel,
      });
      if (hasTimeTarget) {
        cells.push({ label: t`Target`, value: formatTime(rc.target_time_sec!), sub: distLabel });
      }
      cells.push({
        label: <Trans>Current {abbrev}</Trans>,
        value: currentCp != null ? formatThreshold(currentCp, unit) : '—',
        sub: unit,
      });
      if (rCheck.needed_cp != null) {
        cells.push({
          label: <Trans>Needed {abbrev}</Trans>,
          value: formatThreshold(rCheck.needed_cp, unit),
          sub: unit,
        });
      }
      if (rCheck.cp_gap_watts != null) {
        cells.push({
          label: t`Gap`,
          value: `${rCheck.cp_gap_watts > 0 ? '+' : ''}${isPace ? formatPace(Math.abs(rCheck.cp_gap_watts)) : rCheck.cp_gap_watts}`,
          sub: unit,
          tone: severityTone(rCheck.severity),
        });
      }
    } else if (mode === 'cp_milestone') {
      // Track already shows current / target / status. Strip carries only
      // the metrics that aren't visualized: gap, race-time prediction, ETA.
      cells.push({
        label: t`Gap`,
        value: gap != null ? `${gap > 0 ? '+' : ''}${formatThreshold(Math.abs(gap), unit)}` : '—',
        sub: unit,
        tone: gap == null ? undefined : gap > 0 ? 'amber' : 'positive',
      });
      cells.push({
        label: t`Predicted`,
        value: rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '—',
        sub: distLabel,
      });
      cells.push({
        label: t`To target`,
        value: rc.estimated_months != null ? rc.estimated_months.toFixed(1) : '—',
        sub: t`months`,
      });
    } else {
      cells.push({
        label: <Trans>Current {abbrev}</Trans>,
        value: currentCp != null ? formatThreshold(currentCp, unit) : '—',
        sub: unit,
      });
      cells.push({
        label: t`Direction`,
        value: trend ? trendDirectionLabel(trend.direction) : '—',
        sub: trend && trend.slope_per_month !== 0
          ? `${trend.slope_per_month > 0 ? '+' : ''}${isPace ? formatPace(Math.abs(trend.slope_per_month)) : trend.slope_per_month.toFixed(1)}${unit}/mo`
          : undefined,
        tone: severityTone(rCheck.severity),
      });
      if (rc.predicted_time_sec != null) {
        cells.push({
          label: t`Predicted`,
          value: formatTime(rc.predicted_time_sec),
          sub: distLabel,
        });
      }
    }
    return cells;
  })();

  const isUltra = isUltraDistance(rc.distance);

  return (
    <div className="goal-trajectory">
      <p className="goal-eyebrow">
        {eyebrow}
        {rCheck.severity !== 'unknown' && (
          <Badge variant={severityVariant(rCheck.severity)} className="goal-eyebrow-status uppercase tracking-wider">
            {statusLabel}
          </Badge>
        )}
      </p>
      <h2 className="goal-headline">{headline}</h2>

      <div className="goal-cols">
        <div className="goal-col-chart">{chart}</div>
        <div className="goal-col-coach">
          {/* Praxys Coach receipt — single canonical narrative
              surface. AI race-forecast insight when available, the
              deterministic `trend_note` (rule-based reality-check
              prose) otherwise. The receipt always renders so the user
              sees a "why" beneath the headline regardless of AI
              availability. */}
          <AiInsightsCard
            insightType="race_forecast"
            attribution={attribution}
            fallback={rCheck.trend_note ? { headline: rCheck.trend_note } as CoachFallback : undefined}
          />
        </div>
      </div>

      <div className="goal-strip">
        {statCells.map((c, i) => (
          <div key={i} className="goal-strip-cell">
            <span className="goal-strip-label">{c.label}</span>
            <span
              className={`goal-strip-value ${
                c.tone === 'amber'
                  ? 'goal-strip-amber'
                  : c.tone === 'positive'
                    ? 'goal-strip-positive'
                    : c.tone === 'destructive'
                      ? 'goal-strip-destructive'
                      : ''
              }`.trim()}
            >
              {c.value}
            </span>
            {c.sub && <span className="goal-strip-sub">{c.sub}</span>}
          </div>
        ))}
      </div>

{mode === 'race_date' && rCheck.realistic_targets &&
        (rCheck.severity === 'behind' || rCheck.severity === 'unlikely') && (
          <div className="goal-section">
            <p className="goal-section-label"><Trans>Realistic alternative targets</Trans></p>
            <div className="goal-alts-grid">
              <div className="goal-alts-cell">
                <span className="goal-strip-label"><Trans>Comfortable</Trans></span>
                <span className="goal-strip-value goal-strip-positive">{formatTime(rCheck.realistic_targets.comfortable)}</span>
              </div>
              <div className="goal-alts-cell">
                <span className="goal-strip-label"><Trans>Stretch</Trans></span>
                <span className="goal-strip-value goal-strip-amber">{formatTime(rCheck.realistic_targets.stretch)}</span>
              </div>
            </div>
          </div>
        )}

      <ScienceNote text={note.text} sourceUrl={note.url} sourceLabel={t`Source`} />
      {isUltra && <ScienceNote text={ultraNote()} sourceUrl={SCIENCE_ULTRA_URL} sourceLabel={t`Discussion`} />}
    </div>
  );
}

// --- Main Goal Page ---

type GoalType = 'race' | 'continuous';

function GoalSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-8 w-36" />
        <Skeleton className="h-8 w-24" />
      </div>
      <Skeleton className="h-12 w-72" />
      <Skeleton className="h-20 w-full max-w-2xl" />
      <Skeleton className="h-80 rounded-2xl" />
    </div>
  );
}

export default function Goal() {
  const { data, loading, error, refetch } = useApi<GoalResponse>('/api/goal');
  const { isDemo } = useAuth();
  const { config, updateSettings } = useSettings();
  const [isEditing, setIsEditing] = useState(false);

  const currentRaceDate = config?.goal?.race_date ? String(config.goal.race_date) : '';
  const currentDistance = config?.goal?.distance ? String(config.goal.distance) : 'marathon';
  const currentTargetTime = (() => {
    const v = config?.goal?.target_time_sec ?? config?.goal?.race_target_time_sec;
    return v ? Number(v) || null : null;
  })();
  const currentGoalType: GoalType = currentRaceDate ? 'race' : 'continuous';

  const handleSaveGoal = async (goal: { race_date: string; distance: string; target_time_sec: number }) => {
    await updateSettings({ goal });
    refetch();
  };

  if (loading) return <GoalSkeleton />;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold"><Trans>Goal Tracker</Trans></h1>
        {data && (
          <Button variant="outline" size="sm" onClick={() => setIsEditing(true)} disabled={isDemo}>
            <Trans>Change Goal</Trans>
          </Button>
        )}
      </div>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle><Trans>Failed to load goal data</Trans></AlertTitle>
          <AlertDescription className="flex items-center justify-between">
            <span>{error}</span>
            <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
          </AlertDescription>
        </Alert>
      )}

      {isEditing && (
        <GoalEditor
          open={isEditing}
          onOpenChange={setIsEditing}
          initialType={currentGoalType}
          initialRaceDate={currentRaceDate}
          initialDistance={currentDistance}
          initialTargetTime={currentTargetTime}
          onSave={handleSaveGoal}
        />
      )}

      {data && <TrajectoryGoal data={data} />}
    </div>
  );
}
