import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useSettings } from '@/contexts/SettingsContext';
import { Link2, RefreshCw, Gauge, Target, Check } from 'lucide-react';

interface SetupChecklistProps {
  /** Whether data has been synced (last_activity exists or upcoming workouts present). */
  hasData: boolean;
}

interface Step {
  key: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  done: boolean;
  action: { label: string; to: string };
}

export default function SetupChecklist({ hasData }: SetupChecklistProps) {
  const navigate = useNavigate();
  const { config, effectiveThresholds } = useSettings();

  // Derive completion state from settings context
  const hasConnection = Object.values(effectiveThresholds).some(
    (t) => t.origin !== 'none'
  );
  // Connections are "real" if any threshold was auto-detected from a platform,
  // OR if any sync has completed (indicated by hasData).
  // Fallback: check if the user has manually entered any threshold.
  const hasAnyThreshold = Object.values(effectiveThresholds).some(
    (t) => t.value != null
  );
  const platformConnected = hasConnection || hasData || hasAnyThreshold;

  const goalConfigured = config?.goal
    ? (config.goal.race_date && config.goal.race_date !== '') ||
      (config.goal.target_time_sec && Number(config.goal.target_time_sec) > 0)
    : false;

  const steps: Step[] = [
    {
      key: 'connect',
      label: 'Connect a platform',
      description: 'Link Garmin, Stryd, or Oura to pull your training data',
      icon: <Link2 className="h-4 w-4" />,
      done: platformConnected,
      action: { label: 'Connect', to: '/settings' },
    },
    {
      key: 'sync',
      label: 'Sync your data',
      description: 'Pull your latest activities, power data, and recovery metrics',
      icon: <RefreshCw className="h-4 w-4" />,
      done: hasData,
      action: { label: 'Sync', to: '/settings' },
    },
    {
      key: 'base',
      label: 'Choose training base',
      description: `Currently set to ${config?.training_base || 'power'}-based training`,
      icon: <Gauge className="h-4 w-4" />,
      done: true, // Always done — has a default
      action: { label: 'Change', to: '/settings' },
    },
    {
      key: 'goal',
      label: 'Set a goal',
      description: 'Target a race or track continuous improvement',
      icon: <Target className="h-4 w-4" />,
      done: !!goalConfigured,
      action: { label: 'Set goal', to: '/goal' },
    },
  ];

  const completed = steps.filter((s) => s.done).length;
  const allDone = completed === steps.length;

  // Don't render if all setup is complete
  if (allDone) return null;

  const progressPct = (completed / steps.length) * 100;

  return (
    <Card className="border-primary/20 overflow-hidden">
      <CardContent className="pt-5 pb-4">
        {/* Header with progress */}
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-lg font-semibold text-foreground">
              Get started with Trainsight
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              {completed === 0
                ? 'Complete these steps to unlock your training insights'
                : `${completed} of ${steps.length} steps complete`}
            </p>
          </div>
          <span className="text-xs font-semibold font-data text-primary tabular-nums shrink-0 mt-1">
            {completed}/{steps.length}
          </span>
        </div>

        {/* Progress bar */}
        <div className="h-1 w-full rounded-full bg-muted mb-5">
          <div
            className="h-1 rounded-full bg-primary transition-all duration-500 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        {/* Steps */}
        <div className="space-y-1">
          {steps.map((step) => (
            <div
              key={step.key}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors ${
                step.done
                  ? 'opacity-60'
                  : 'hover:bg-muted/50'
              }`}
            >
              {/* Status icon */}
              <div
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                  step.done
                    ? 'bg-primary/15 text-primary'
                    : 'bg-muted text-muted-foreground'
                }`}
              >
                {step.done ? (
                  <Check className="h-3.5 w-3.5" strokeWidth={3} />
                ) : (
                  step.icon
                )}
              </div>

              {/* Text */}
              <div className="flex-1 min-w-0">
                <p
                  className={`text-sm font-medium ${
                    step.done
                      ? 'text-muted-foreground line-through decoration-muted-foreground/40'
                      : 'text-foreground'
                  }`}
                >
                  {step.label}
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  {step.description}
                </p>
              </div>

              {/* Action */}
              {!step.done && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-xs text-primary hover:text-primary hover:bg-primary/10"
                  onClick={() => navigate(step.action.to)}
                >
                  {step.action.label}
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
