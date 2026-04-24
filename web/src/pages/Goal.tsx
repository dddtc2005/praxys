import { useState } from 'react';
import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { useSettings } from '@/contexts/SettingsContext';
import type { GoalResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import GoalEditor from '@/components/GoalEditor';
import CliHint from '@/components/CliHint';
import MilestoneTracker from '@/components/MilestoneTracker';
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

function severityColor(severity: string): string {
  switch (severity as Severity) {
    case 'on_track': return 'text-primary';
    case 'close': return 'text-accent-amber';
    case 'behind':
    case 'unlikely': return 'text-destructive';
    default: return 'text-muted-foreground';
  }
}

function severityVariant(severity: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (severity as Severity) {
    case 'on_track': return 'default';
    case 'close': return 'secondary';
    case 'behind':
    case 'unlikely': return 'destructive';
    default: return 'outline';
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

// --- Tracking Modes ---

function RaceDateMode({ data }: { data: GoalResponse }) {
  const { t, i18n } = useLingui();
  const predictionNote = usePredictionNote();
  const ultraNote = useUltraNote();
  const rc = data.race_countdown;
  const rCheck = rc.reality_check;
  const hasTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const distLabel = rc.distance_label ? tDisplay(rc.distance_label, i18n) : t`Race`;
  const d = data.display;
  const unit = d?.threshold_unit || 'W';
  const abbrev = d?.threshold_abbrev || 'CP';
  const note = predictionNote(data.training_base, data.science_notes);

  return (
    <div className="space-y-4">
      {/* Hero: Countdown */}
      <Card>
        <CardContent className="pt-6 text-center">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            <Trans>{distLabel} Countdown</Trans>
          </h3>
          <div className="flex flex-col items-center gap-2">
            <span className="font-data text-6xl font-bold text-foreground">
              {rc.days_left ?? '\u2014'}
            </span>
            <span className="text-sm text-muted-foreground">
              <Trans>days until {rc.race_date ?? t`race day`}</Trans>
            </span>
            <Badge variant={severityVariant(rCheck.severity)} className="uppercase tracking-wider">
              {rc.status.replace(/_/g, ' ')}
            </Badge>
          </div>

          <div className={`mt-6 grid gap-4 ${hasTarget ? 'grid-cols-2' : 'grid-cols-1'}`}>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1"><Trans>Predicted {distLabel}</Trans></p>
              <p className="font-data text-2xl text-foreground">
                {rc.predicted_time_sec != null ? formatTime(rc.predicted_time_sec) : '\u2014'}
              </p>
            </div>
            {hasTarget && (
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1"><Trans>Target</Trans></p>
                <p className="font-data text-2xl text-foreground">
                  {formatTime(rc.target_time_sec!)}
                </p>
              </div>
            )}
          </div>
          <ScienceNote text={note.text} sourceUrl={note.url} sourceLabel={t`Source`} />
          {isUltraDistance(data.race_countdown.distance) && (
            <ScienceNote text={ultraNote()} sourceUrl={SCIENCE_ULTRA_URL} sourceLabel={t`Discussion`} />
          )}
        </CardContent>
      </Card>

      {/* Reality Check */}
      {hasTarget && rCheck.severity !== 'unknown' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Reality Check</Trans></CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
              {rCheck.assessment}
            </p>

            {rCheck.current_cp != null && rCheck.needed_cp != null && (
              <div className="flex items-center gap-4 rounded-lg bg-muted px-4 py-3">
                <div className="text-center">
                  <p className="text-xs text-muted-foreground"><Trans>Current {abbrev}</Trans></p>
                  <p className="font-data text-lg text-foreground">{formatThreshold(rCheck.current_cp, unit)}{unit}</p>
                </div>
                <div className="text-muted-foreground">&rarr;</div>
                <div className="text-center">
                  <p className="text-xs text-muted-foreground"><Trans>Needed {abbrev}</Trans></p>
                  <p className="font-data text-lg text-foreground">{formatThreshold(rCheck.needed_cp, unit)}{unit}</p>
                </div>
                {rCheck.cp_gap_watts != null && (
                  <div className="ml-auto text-center">
                    <p className="text-xs text-muted-foreground"><Trans>Gap</Trans></p>
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
                    <Trans>Realistic Alternative Targets</Trans>
                  </p>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-xs text-muted-foreground"><Trans>Comfortable</Trans></p>
                      <p className="font-data text-lg text-primary">
                        {formatTime(rCheck.realistic_targets.comfortable)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground"><Trans>Stretch</Trans></p>
                      <p className="font-data text-lg text-accent-amber">
                        {formatTime(rCheck.realistic_targets.stretch)}
                      </p>
                    </div>
                  </div>
                </div>
              )}
          </CardContent>
        </Card>
      )}

      {/* Trend-based assessment when no target */}
      {!hasTarget && rCheck.trend_note && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Fitness Trend</Trans></CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
              {rCheck.assessment}
            </p>
            <p className="text-sm text-muted-foreground mt-2">{rCheck.trend_note}</p>
          </CardContent>
        </Card>
      )}

      <DataHint sufficient={data.data_meta?.cp_trend_sufficient ?? true} message={t`Not enough data to show CP trend`} hint={t`Need at least 3 activities with power data.`}><CpTrendChart data={data.cp_trend} targetCp={rc.target_cp} label={d?.trend_label} unit={d?.threshold_unit} metricName={d?.threshold_abbrev} /></DataHint>
    </div>
  );
}

function CpMilestoneMode({ data }: { data: GoalResponse }) {
  const { t, i18n } = useLingui();
  const predictionNote = usePredictionNote();
  const ultraNote = useUltraNote();
  const rc = data.race_countdown;
  const rCheck = rc.reality_check;
  const currentCp = data.latest_cp;
  const targetCp = rc.target_cp ?? null;
  const distLabel = rc.distance_label ? tDisplay(rc.distance_label, i18n) : t`Race`;
  const hasTimeTarget = rc.target_time_sec != null && rc.target_time_sec > 0;
  const d = data.display;
  const unit = d?.threshold_unit || 'W';
  const isPace = unit === '/km';
  const note = predictionNote(data.training_base, data.science_notes);

  const progressPct = (() => {
    if (currentCp == null || targetCp == null || targetCp <= 0) return 0;
    if (isPace) return Math.min(100, Math.max(0, (targetCp / currentCp) * 100));
    return Math.min(100, Math.max(0, (currentCp / targetCp) * 100));
  })();

  return (
    <div className="space-y-4">
      {/* Hero: Target + Progress */}
      <Card>
        <CardContent className="pt-6 text-center">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            {hasTimeTarget
              ? <Trans>Building toward {formatTime(rc.target_time_sec!)} {distLabel}</Trans>
              : <Trans>{distLabel} Progress</Trans>}
          </h3>

          {rc.predicted_time_sec != null && (
            <div className={`grid gap-4 mb-4 ${hasTimeTarget ? 'grid-cols-2' : 'grid-cols-1'}`}>
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1"><Trans>Predicted {distLabel}</Trans></p>
                <p className="font-data text-2xl text-foreground">{formatTime(rc.predicted_time_sec)}</p>
              </div>
              {hasTimeTarget && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1"><Trans>Target</Trans></p>
                  <p className="font-data text-2xl text-foreground">{formatTime(rc.target_time_sec!)}</p>
                </div>
              )}
            </div>
          )}

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
                <Progress value={progressPct} className="h-4" />
                <p className="text-xs text-muted-foreground mt-1 font-data">{progressPct.toFixed(0)}%</p>
              </div>
            </>
          )}

          <div className="mt-3">
            <Badge variant={severityVariant(rCheck.severity)} className="uppercase tracking-wider">
              {rc.status.replace(/_/g, ' ')}
            </Badge>
          </div>
          <ScienceNote text={note.text} sourceUrl={note.url} sourceLabel={t`Source`} />
          {isUltraDistance(data.race_countdown.distance) && (
            <ScienceNote text={ultraNote()} sourceUrl={SCIENCE_ULTRA_URL} sourceLabel={t`Discussion`} />
          )}
        </CardContent>
      </Card>

      {/* Milestones */}
      {rc.milestones && rc.milestones.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Milestones</Trans></CardTitle>
          </CardHeader>
          <CardContent>
            <MilestoneTracker milestones={rc.milestones} currentCp={currentCp} targetCp={targetCp} />
          </CardContent>
        </Card>
      )}

      {/* Assessment */}
      <Card>
        <CardHeader>
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Assessment</Trans></CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
            {rCheck.assessment}
          </p>
          {rc.estimated_months != null && (
            <div className="rounded-lg bg-muted px-4 py-3">
              <p className="text-xs text-muted-foreground"><Trans>Estimated time to target</Trans></p>
              <p className="font-data text-lg text-foreground">
                <Trans>{rc.estimated_months.toFixed(1)} months</Trans>
              </p>
            </div>
          )}
          {rCheck.trend_note && (
            <p className="text-sm text-muted-foreground">{rCheck.trend_note}</p>
          )}
        </CardContent>
      </Card>

      <DataHint sufficient={data.data_meta?.cp_trend_sufficient ?? true} message={t`Not enough data to show CP trend`} hint={t`Need at least 3 activities with power data.`}><CpTrendChart data={data.cp_trend} targetCp={targetCp} label={d?.trend_label} unit={d?.threshold_unit} metricName={d?.threshold_abbrev} /></DataHint>
    </div>
  );
}

function ContinuousMode({ data }: { data: GoalResponse }) {
  const { t, i18n } = useLingui();
  const predictionNote = usePredictionNote();
  const ultraNote = useUltraNote();
  const trendDirectionLabel = useTrendDirectionLabel();
  const rc = data.race_countdown;
  const rCheck = rc.reality_check;
  const currentCp = data.latest_cp;
  const trend = rc.cp_trend_summary;
  const distLabel = rc.distance_label ? tDisplay(rc.distance_label, i18n) : t`Marathon`;
  const d = data.display;
  const unit = d?.threshold_unit || 'W';
  const note = predictionNote(data.training_base, data.science_notes);

  return (
    <div className="space-y-4">
      {/* Hero: Current Threshold + Predicted Time */}
      <Card>
        <CardContent className="pt-6 text-center">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            <Trans>Current Fitness</Trans>
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

          {rc.predicted_time_sec != null && (
            <div className="mt-4 pt-4 border-t border-border">
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1"><Trans>Predicted {distLabel}</Trans></p>
              <p className="font-data text-2xl text-foreground">{formatTime(rc.predicted_time_sec)}</p>
            </div>
          )}
          <ScienceNote text={note.text} sourceUrl={note.url} sourceLabel={t`Source`} />
          {isUltraDistance(data.race_countdown.distance) && (
            <ScienceNote text={ultraNote()} sourceUrl={SCIENCE_ULTRA_URL} sourceLabel={t`Discussion`} />
          )}
        </CardContent>
      </Card>

      {/* Assessment */}
      {rCheck.trend_note && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Trend</Trans></CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-sm font-medium ${severityColor(rCheck.severity)}`}>
              {rCheck.assessment}
            </p>
            <p className="text-sm text-muted-foreground mt-2">{rCheck.trend_note}</p>
          </CardContent>
        </Card>
      )}

      <DataHint sufficient={data.data_meta?.cp_trend_sufficient ?? true} message={t`Not enough data to show CP trend`} hint={t`Need at least 3 activities with power data.`}><CpTrendChart data={data.cp_trend} label={d?.trend_label} unit={d?.threshold_unit} metricName={d?.threshold_abbrev} /></DataHint>
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
      <Skeleton className="h-64 rounded-2xl" />
      <Skeleton className="h-48 rounded-2xl" />
      <Skeleton className="h-80 rounded-2xl" />
    </div>
  );
}

export default function Goal() {
  const { t } = useLingui();
  const { data, loading, error, refetch } = useApi<GoalResponse>('/api/goal');
  const { isDemo } = useAuth();
  const { config, updateSettings } = useSettings();
  const [isEditing, setIsEditing] = useState(false);

  const mode = data?.race_countdown.mode;

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

      {data && (
        <>
          {mode === 'race_date' && <RaceDateMode data={data} />}
          {mode === 'cp_milestone' && <CpMilestoneMode data={data} />}
          {(mode === 'continuous' || mode === 'none') && <ContinuousMode data={data} />}
        </>
      )}

      <CliHint
        skill="race-forecast"
        title={t`AI Race Forecast`}
        description={t`Get a detailed race prediction, goal feasibility analysis, and what you need to improve.`}
      />
    </div>
  );
}
