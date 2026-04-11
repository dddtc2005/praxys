import { useState, useEffect, useCallback } from 'react';
import { useApi } from '@/hooks/useApi';
import type { PlanResponse, PlannedWorkout, StrydPushStatus, StrydPushResult } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

const TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  easy:       { bg: 'bg-primary/15', text: 'text-primary' },
  recovery:   { bg: 'bg-primary/15', text: 'text-primary' },
  long:       { bg: 'bg-accent-blue/15',  text: 'text-accent-blue' },
  tempo:      { bg: 'bg-accent-amber/15', text: 'text-accent-amber' },
  threshold:  { bg: 'bg-accent-amber/15', text: 'text-accent-amber' },
  interval:   { bg: 'bg-destructive/15',   text: 'text-destructive' },
  repetition: { bg: 'bg-destructive/15',   text: 'text-destructive' },
};

const DEFAULT_COLOR = { bg: 'bg-accent-purple/15', text: 'text-accent-purple' };

function getTypeColor(type: string) {
  const key = type.toLowerCase().replace(/\s+/g, ' ');
  if (TYPE_COLORS[key]) return TYPE_COLORS[key];
  for (const [k, v] of Object.entries(TYPE_COLORS)) {
    if (key.includes(k)) return v;
  }
  return DEFAULT_COLOR;
}

function formatType(type: string): string {
  return type
    .split(/[\s_]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function formatDate(dateStr: string): { day: string; weekday: string; isToday: boolean } {
  const d = new Date(dateStr + 'T00:00:00');
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isToday = d.getTime() === today.getTime();
  return {
    day: d.getDate().toString().padStart(2, '0'),
    weekday: d.toLocaleDateString('en-US', { weekday: 'short' }).toUpperCase(),
    isToday,
  };
}

type PushState = 'none' | 'pushed' | 'pushing' | 'error';

const UploadIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M8 2v8M5 7l3-3 3 3M3 12h10" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const SpinnerIcon = ({ className }: { className?: string }) => (
  <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
);

const CheckIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 8.5l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const ErrorIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="currentColor">
    <path d="M8 1a7 7 0 100 14A7 7 0 008 1zM7 5h2v4H7V5zm0 5h2v2H7v-2z" />
  </svg>
);

const RefreshIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M2.5 8a5.5 5.5 0 019.3-4M13.5 8a5.5 5.5 0 01-9.3 4" strokeLinecap="round" />
    <path d="M12 1.5v3h-3M4 11.5v3h3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

function StrydStatusBadge({
  state,
  error,
  onPush,
  showStryd,
}: {
  state: PushState;
  error?: string;
  onPush?: () => void;
  showStryd: boolean;
}) {
  if (!showStryd) return null;

  if (state === 'pushing') {
    return (
      <div className="w-6 h-6 flex items-center justify-center shrink-0">
        <SpinnerIcon className="h-3.5 w-3.5 text-muted-foreground" />
      </div>
    );
  }

  if (state === 'error') {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger
            render={(
              <Button
                variant="ghost"
                size="icon"
                onClick={onPush}
                aria-label="Retry push to Stryd"
                className="w-6 h-6 shrink-0 text-destructive hover:text-destructive/80"
              >
                <ErrorIcon className="h-3.5 w-3.5" />
              </Button>
            )}
          />
          <TooltipContent side="left">
            <p className="text-xs">{error || 'Push failed'} — click to retry</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  if (state === 'pushed') {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger
            render={(
              <Button
                variant="ghost"
                size="icon"
                onClick={onPush}
                aria-label="Re-push to Stryd"
                className="w-6 h-6 shrink-0 text-primary [&>svg.check]:block [&>svg.refresh]:hidden hover:[&>svg.check]:hidden hover:[&>svg.refresh]:block hover:text-accent-amber"
              >
                <CheckIcon className="check h-3.5 w-3.5" />
                <RefreshIcon className="refresh h-3.5 w-3.5" />
              </Button>
            )}
          />
          <TooltipContent side="left">
            <p className="text-xs">Re-push to Stryd</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // state === 'none' — show push button on hover
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={(
            <Button
              variant="ghost"
              size="icon"
              onClick={onPush}
              aria-label="Push to Stryd"
              className="w-6 h-6 shrink-0 text-muted-foreground/0 group-hover:text-muted-foreground hover:!text-primary"
            >
              <UploadIcon className="h-3.5 w-3.5" />
            </Button>
          )}
        />
        <TooltipContent side="left">
          <p className="text-xs">Push to Stryd</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function WorkoutRow({
  workout,
  pushState,
  pushError,
  showStryd,
  onPushSingle,
}: {
  workout: PlannedWorkout;
  pushState: PushState;
  pushError?: string;
  showStryd: boolean;
  onPushSingle: (date: string) => void;
}) {
  const { day, weekday, isToday } = formatDate(workout.date);
  const color = getTypeColor(workout.workout_type);
  const isRest = workout.workout_type.toLowerCase() === 'rest';

  const details: string[] = [];
  if (workout.duration_min != null) details.push(`${Math.round(workout.duration_min)}m`);
  if (workout.distance_km != null) details.push(`${workout.distance_km}km`);
  if (workout.power_min != null && workout.power_max != null)
    details.push(`${workout.power_min}\u2013${workout.power_max}W`);

  return (
    <div
      className={`group flex items-center gap-3 py-2.5 px-3 rounded-lg transition-colors ${
        isToday
          ? 'bg-primary/5 ring-1 ring-accent-green/20'
          : 'hover:bg-muted/50'
      }`}
    >
      {/* Date column */}
      <div className="flex flex-col items-center w-10 shrink-0">
        <span className={`text-[10px] font-semibold tracking-wider ${
          isToday ? 'text-primary' : 'text-muted-foreground'
        }`}>
          {isToday ? 'TODAY' : weekday}
        </span>
        <span className={`font-data text-lg leading-tight ${
          isToday ? 'text-primary font-bold' : 'text-muted-foreground'
        }`}>
          {day}
        </span>
      </div>

      {/* Divider */}
      <div className={`w-px h-8 ${isToday ? 'bg-primary/30' : 'bg-border'}`} />

      {/* Type badge + details */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${color.bg} ${color.text}`}>
            {formatType(workout.workout_type)}
          </span>
          {details.length > 0 && (
            <span className="font-data text-xs text-muted-foreground truncate">
              {details.join(' · ')}
            </span>
          )}
        </div>
        {workout.description && (
          <p className="text-xs text-muted-foreground mt-0.5 truncate">{workout.description}</p>
        )}
      </div>

      {/* Stryd sync status / push button */}
      {!isRest && (
        <StrydStatusBadge
          state={pushState}
          error={pushError}
          showStryd={showStryd}
          onPush={() => onPushSingle(workout.date)}
        />
      )}
    </div>
  );
}

async function pushDatesToStryd(dates: string[]): Promise<{
  results: StrydPushResult[];
}> {
  const resp = await fetch('/api/plan/push-stryd', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workout_dates: dates }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

export default function UpcomingPlanCard() {
  const { data, loading, error, refetch } = useApi<PlanResponse>('/api/plan');
  const [pushStatus, setPushStatus] = useState<StrydPushStatus>({});
  const [pushErrors, setPushErrors] = useState<Record<string, string>>({});
  const [pushing, setPushing] = useState(false);
  const [pushingDates, setPushingDates] = useState<Set<string>>(new Set());
  const [hasStryd, setHasStryd] = useState(false);

  // Check if Stryd is connected
  useEffect(() => {
    fetch('/api/settings')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((config) => {
        if (config?.config?.connections?.includes('stryd')) setHasStryd(true);
      })
      .catch((err) => console.error('Failed to load settings:', err));
  }, []);

  // Load push status
  useEffect(() => {
    fetch('/api/plan/stryd-status')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((status) => setPushStatus(status))
      .catch((err) => console.error('Failed to load Stryd push status:', err));
  }, []);

  const getPushState = useCallback(
    (date: string): PushState => {
      if (pushingDates.has(date)) return 'pushing';
      if (pushErrors[date]) return 'error';
      if (pushStatus[date]) return 'pushed';
      return 'none';
    },
    [pushingDates, pushErrors, pushStatus],
  );

  const handlePushResults = useCallback(
    (results: StrydPushResult[], dates: string[]) => {
      setPushStatus((prev) => {
        const next = { ...prev };
        for (const r of results) {
          if (r.status === 'success') {
            next[r.date] = {
              workout_id: r.workout_id,
              pushed_at: new Date().toISOString(),
              status: 'pushed',
            };
          }
        }
        return next;
      });

      setPushErrors((prev) => {
        const next = { ...prev };

        // Clear errors for dates we just retried
        for (const d of dates) delete next[d];

        for (const r of results) {
          if (r.status === 'success') {
            delete next[r.date];
          } else {
            next[r.date] = r.error;
          }
        }

        return next;
      });
    },
    [],
  );

  // Push a single workout (or re-push by deleting old one first)
  const pushSingle = useCallback(
    async (date: string) => {
      if (pushingDates.has(date)) return;

      setPushingDates((prev) => new Set(prev).add(date));

      try {
        // If already pushed, delete the old workout from Stryd first
        const existing = pushStatus[date];
        if (existing?.workout_id) {
          const resp = await fetch(`/api/plan/stryd-workout/${existing.workout_id}`, { method: 'DELETE' });
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
          }
          setPushStatus((prev) => {
            const next = { ...prev };
            delete next[date];
            return next;
          });
        }

        const { results } = await pushDatesToStryd([date]);
        handlePushResults(results, [date]);
      } catch (e) {
        setPushErrors((prev) => ({
          ...prev,
          [date]: e instanceof Error ? e.message : 'Push failed',
        }));
      } finally {
        setPushingDates((prev) => {
          const next = new Set(prev);
          next.delete(date);
          return next;
        });
      }
    },
    [pushingDates, pushStatus, handlePushResults],
  );

  // Push all unpushed workouts
  const pushAll = useCallback(async () => {
    if (!data) return;

    const datesToPush = data.workouts
      .filter((w) => !pushStatus[w.date] && w.workout_type.toLowerCase() !== 'rest')
      .map((w) => w.date);

    if (datesToPush.length === 0) return;

    setPushing(true);
    setPushingDates(new Set(datesToPush));
    setPushErrors({});

    try {
      const { results } = await pushDatesToStryd(datesToPush);
      handlePushResults(results, datesToPush);
    } catch (e) {
      const newErrors: Record<string, string> = {};
      for (const d of datesToPush) {
        newErrors[d] = e instanceof Error ? e.message : 'Push failed';
      }
      setPushErrors(newErrors);
    } finally {
      setPushing(false);
      setPushingDates(new Set());
    }
  }, [data, pushStatus, handlePushResults]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-4 w-32" />
        </CardHeader>
        <CardContent className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="pt-4 flex items-center justify-between">
          <div>
            <p className="text-sm text-destructive">Failed to load training plan</p>
            <p className="text-xs text-muted-foreground">{error}</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => refetch()}>Retry</Button>
        </CardContent>
      </Card>
    );
  }

  if (!data || data.workouts.length === 0) return null;

  const unpushedCount = data.workouts.filter(
    (w) => !pushStatus[w.date] && w.workout_type.toLowerCase() !== 'rest',
  ).length;
  const allPushed = unpushedCount === 0;

  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between space-y-0">
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Upcoming Plan
        </CardTitle>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground font-data">
            {data.workouts.length} workouts
          </span>
          {hasStryd && (
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-[10px] font-semibold uppercase tracking-wider gap-1"
              disabled={pushing || allPushed}
              onClick={pushAll}
            >
              {pushing ? (
                <>
                  <SpinnerIcon className="h-3 w-3" />
                  Pushing...
                </>
              ) : allPushed ? (
                <>
                  <CheckIcon className="h-3 w-3" />
                  Synced
                </>
              ) : (
                <>
                  <UploadIcon className="h-3 w-3" />
                  Push All
                  {unpushedCount > 0 && (
                    <span className="font-data ml-0.5">({unpushedCount})</span>
                  )}
                </>
              )}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-0.5">
          {data.workouts.map((w) => (
            <WorkoutRow
              key={w.date}
              workout={w}
              pushState={getPushState(w.date)}
              pushError={pushErrors[w.date]}
              showStryd={hasStryd}
              onPushSingle={pushSingle}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
