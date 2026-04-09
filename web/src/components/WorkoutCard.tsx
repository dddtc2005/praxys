import { useState } from 'react';
import type { PlanData, UpcomingWorkout } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Badge } from '@/components/ui/badge';
import { ChevronRight } from 'lucide-react';
import WorkoutTimeline from '@/components/WorkoutTimeline';
import { parseWorkoutStructure } from '@/lib/workout-parser';

interface Props {
  plan: PlanData;
  alternatives: string[];
  upcoming?: UpcomingWorkout[];
}

function formatType(type: string): string {
  return type
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDay(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

export default function WorkoutCard({ plan, alternatives, upcoming }: Props) {
  const [showAlts, setShowAlts] = useState(false);
  const [showUpcoming, setShowUpcoming] = useState(false);

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

  const phases = plan.workout_type ? parseWorkoutStructure(plan) : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Planned Workout
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold text-foreground mb-2">{title}</p>

        {details.length > 0 && (
          <p className="text-sm text-muted-foreground mb-1">
            {details.join(' \u00b7 ')}
          </p>
        )}

        {phases.length > 0 && (
          <WorkoutTimeline
            phases={phases}
            powerMin={plan.power_min ?? undefined}
            powerMax={plan.power_max ?? undefined}
          />
        )}

        {plan.description && (
          <p className="text-sm text-muted-foreground leading-relaxed">{plan.description}</p>
        )}

        {alternatives.length > 0 && (
          <Collapsible open={showAlts} onOpenChange={setShowAlts} className="mt-4 border-t border-border pt-3">
            <CollapsibleTrigger className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors">
              <ChevronRight className={`h-3 w-3 transition-transform ${showAlts ? 'rotate-90' : ''}`} />
              Options
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className="mt-2 space-y-1">
                {alternatives.map((alt, i) => (
                  <li key={i} className="text-sm text-muted-foreground pl-4">
                    &bull; {alt}
                  </li>
                ))}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        )}

        {upcoming && upcoming.length > 0 && (
          <Collapsible open={showUpcoming} onOpenChange={setShowUpcoming} className="mt-4 border-t border-border pt-3">
            <CollapsibleTrigger className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors">
              <ChevronRight className={`h-3 w-3 transition-transform ${showUpcoming ? 'rotate-90' : ''}`} />
              Coming Up
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-2 space-y-1.5">
                {upcoming.map((w, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="text-[11px] font-data text-muted-foreground w-24 shrink-0">
                      {formatDay(w.date)}
                    </span>
                    <Badge variant="secondary" className="text-[10px]">
                      {formatType(w.workout_type)}
                    </Badge>
                    {w.duration_min != null && (
                      <span className="text-[11px] font-data text-muted-foreground ml-auto">
                        {w.duration_min}m
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  );
}
