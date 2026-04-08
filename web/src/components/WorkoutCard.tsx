import { useState } from 'react';
import type { PlanData } from '@/types/api';

interface Props {
  plan: PlanData;
  alternatives: string[];
}

export default function WorkoutCard({ plan, alternatives }: Props) {
  const [showAlts, setShowAlts] = useState(false);

  const title = plan.workout_type
    ? plan.workout_type
        .split('_')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ')
    : 'No Workout';

  const details: string[] = [];
  if (plan.duration_min != null) details.push(`${plan.duration_min} min`);
  if (plan.distance_km != null) details.push(`${plan.distance_km} km`);
  if (plan.power_min != null && plan.power_max != null)
    details.push(`${plan.power_min}\u2013${plan.power_max} W`);

  return (
    <div className="rounded-2xl bg-card p-5 sm:p-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
        Planned Workout
      </h3>

      <p className="text-2xl font-bold text-foreground mb-2">{title}</p>

      {details.length > 0 && (
        <p className="text-sm text-muted-foreground mb-3">
          {details.join(' \u00b7 ')}
        </p>
      )}

      {plan.description && (
        <p className="text-sm text-muted-foreground leading-relaxed">{plan.description}</p>
      )}

      {alternatives.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <button
            type="button"
            onClick={() => setShowAlts((v) => !v)}
            className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-muted-foreground transition-colors"
          >
            <span className={`inline-block transition-transform ${showAlts ? 'rotate-90' : ''}`}>
              &#9654;
            </span>
            Options
          </button>
          {showAlts && (
            <ul className="mt-2 space-y-1">
              {alternatives.map((alt, i) => (
                <li key={i} className="text-sm text-muted-foreground pl-4">
                  &bull; {alt}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
