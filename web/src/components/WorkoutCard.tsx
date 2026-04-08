import { useState } from 'react';
import type { PlanData } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ChevronRight } from 'lucide-react';

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
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Planned Workout
        </CardTitle>
      </CardHeader>
      <CardContent>
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
      </CardContent>
    </Card>
  );
}
