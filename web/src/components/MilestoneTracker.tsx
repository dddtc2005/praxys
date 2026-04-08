import { CheckCircle, Circle } from 'lucide-react';
import type { Milestone } from '@/types/api';

interface Props {
  milestones: Milestone[];
  currentCp: number | null;
  targetCp: number | null;
}

export default function MilestoneTracker({ milestones, currentCp, targetCp }: Props) {
  const progressPct =
    currentCp != null && targetCp != null && targetCp > 0
      ? Math.min(100, Math.max(0, (currentCp / targetCp) * 100))
      : 0;

  const barColor =
    progressPct >= 90
      ? 'bg-primary'
      : progressPct >= 70
        ? 'bg-accent-amber'
        : 'bg-destructive';

  return (
    <div className="space-y-5">
      {/* Progress bar */}
      {currentCp != null && targetCp != null && (
        <div>
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
            <span>
              Current: <span className="font-data text-foreground">{currentCp}W</span>
            </span>
            <span>
              Target: <span className="font-data text-foreground">{targetCp}W</span>
            </span>
          </div>
          <div className="h-3 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${barColor}`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground mt-1 text-right font-data">
            {progressPct.toFixed(0)}%
          </p>
        </div>
      )}

      {/* Milestone checklist */}
      <div className="space-y-2">
        {milestones.map((ms) => {
          const isCurrent = currentCp != null && ms.cp === currentCp;
          return (
            <div
              key={ms.cp}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 transition-colors ${
                isCurrent ? 'bg-muted ring-1 ring-accent-green/30' : ''
              }`}
            >
              {ms.reached ? (
                <CheckCircle className="h-5 w-5 shrink-0 text-primary" />
              ) : (
                <Circle className="h-5 w-5 shrink-0 text-muted-foreground" />
              )}
              <span className="font-data text-sm text-foreground">{ms.cp}W</span>
              <span className="text-sm text-muted-foreground">{ms.marathon}</span>
              {isCurrent && (
                <span className="ml-auto rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">
                  Current
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
