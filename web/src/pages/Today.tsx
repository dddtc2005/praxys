import { useApi } from '@/hooks/useApi';
import type { TodayResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { AlertTriangle } from 'lucide-react';
import SignalHero from '@/components/SignalHero';
import RecoveryPanel from '@/components/RecoveryPanel';
import WorkoutCard from '@/components/WorkoutCard';
import FormSparkline from '@/components/charts/FormSparkline';
import LastActivityCard from '@/components/LastActivityCard';
import WeeklyLoadMini from '@/components/WeeklyLoadMini';

function TodaySkeleton() {
  return (
    <div className="space-y-6">
      <div>
        <Skeleton className="h-8 w-24" />
        <Skeleton className="h-4 w-48 mt-2" />
      </div>
      <Skeleton className="h-60 w-full rounded-2xl" />
      <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
        <Skeleton className="h-48 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
      <Skeleton className="h-32 w-full rounded-2xl" />
    </div>
  );
}

export default function Today() {
  const { data, loading, error } = useApi<TodayResponse>('/api/today');

  const now = new Date();
  const dateStr = now.toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  if (loading) return <TodaySkeleton />;

  if (error) {
    return (
      <Alert variant="destructive" className="my-12">
        <AlertTitle>Failed to load</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!data) return null;

  const { signal, tsb_sparkline, warnings } = data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">Today</h1>
        <p className="text-sm text-muted-foreground mt-1">{dateStr}</p>
      </div>

      {/* Signal Hero — full width */}
      <SignalHero recommendation={signal.recommendation} reason={signal.reason} />

      {/* Two-column grid: Recovery + Workout */}
      <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
        <RecoveryPanel recovery={signal.recovery} theoryMeta={data.recovery_theory} analysis={data.recovery_analysis} />
        <WorkoutCard plan={signal.plan} alternatives={signal.alternatives} upcoming={data.upcoming} />
      </div>

      {/* Form sparkline — full width */}
      <FormSparkline data={tsb_sparkline} />

      {/* Context row: Last Activity + Weekly Load */}
      {(data.last_activity || data.week_load) && (
        <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
          {data.last_activity && <LastActivityCard activity={data.last_activity} />}
          {data.week_load && <WeeklyLoadMini weekLoad={data.week_load} />}
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Warnings
          </h3>
          {warnings.map((w, i) => (
            <Alert key={i} className="border-accent-amber/30 bg-accent-amber/5 text-accent-amber [&>svg]:text-accent-amber">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{w}</AlertDescription>
            </Alert>
          ))}
        </div>
      )}
    </div>
  );
}
