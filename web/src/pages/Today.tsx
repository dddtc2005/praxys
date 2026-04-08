import { useApi } from '@/hooks/useApi';
import type { TodayResponse } from '@/types/api';
import SignalHero from '@/components/SignalHero';
import RecoveryPanel from '@/components/RecoveryPanel';
import WorkoutCard from '@/components/WorkoutCard';
import FormSparkline from '@/components/charts/FormSparkline';

function Spinner() {
  return (
    <div className="flex items-center justify-center py-24">
      <div className="h-10 w-10 rounded-full border-4 border-border border-t-accent-green animate-spin" />
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

  if (loading) return <Spinner />;

  if (error) {
    return (
      <div className="py-12 text-center">
        <p className="text-destructive text-lg font-semibold">Failed to load</p>
        <p className="text-muted-foreground text-sm mt-1">{error}</p>
      </div>
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
        <RecoveryPanel recovery={signal.recovery} />
        <WorkoutCard plan={signal.plan} alternatives={signal.alternatives} />
      </div>

      {/* Form sparkline — full width */}
      <FormSparkline data={tsb_sparkline} />

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Warnings
          </h3>
          {warnings.map((w, i) => (
            <div
              key={i}
              className="rounded-xl border border-accent-amber/30 bg-accent-amber/5 px-4 py-3 text-sm text-accent-amber"
            >
              {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
