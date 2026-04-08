import { useApi } from '@/hooks/useApi';
import type { PlanResponse, PlannedWorkout } from '@/types/api';

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
  // Check exact match first, then partial
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

function WorkoutRow({ workout }: { workout: PlannedWorkout }) {
  const { day, weekday, isToday } = formatDate(workout.date);
  const color = getTypeColor(workout.workout_type);

  const details: string[] = [];
  if (workout.duration_min != null) details.push(`${Math.round(workout.duration_min)}m`);
  if (workout.distance_km != null) details.push(`${workout.distance_km}km`);
  if (workout.power_min != null && workout.power_max != null)
    details.push(`${workout.power_min}\u2013${workout.power_max}W`);

  return (
    <div
      className={`flex items-center gap-3 py-2.5 px-3 rounded-lg transition-colors ${
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
    </div>
  );
}

export default function UpcomingPlanCard() {
  const { data, loading, error } = useApi<PlanResponse>('/api/plan');

  if (loading) {
    return (
      <div className="rounded-2xl bg-card p-5 sm:p-6">
        <div className="h-6 w-32 bg-muted rounded animate-pulse mb-4" />
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-12 bg-muted rounded-lg animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data || data.workouts.length === 0) return null;

  return (
    <div className="rounded-2xl bg-card p-5 sm:p-6">
      <div className="flex items-baseline justify-between mb-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Upcoming Plan
        </h3>
        <span className="text-xs text-muted-foreground font-data">
          {data.workouts.length} workouts
        </span>
      </div>

      <div className="space-y-0.5">
        {data.workouts.map((w) => (
          <WorkoutRow key={w.date} workout={w} />
        ))}
      </div>
    </div>
  );
}
