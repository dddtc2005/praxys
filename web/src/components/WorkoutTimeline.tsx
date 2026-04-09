import type { WorkoutPhase, Intensity } from '@/lib/workout-parser';
import { useChartColors } from '@/hooks/useChartColors';

interface Props {
  phases: WorkoutPhase[];
  powerMin?: number;
  powerMax?: number;
}

const INTENSITY_HEIGHT: Record<Intensity, string> = {
  rest: 'h-3',
  easy: 'h-5',
  moderate: 'h-7',
  hard: 'h-9',
  very_hard: 'h-11',
};

export default function WorkoutTimeline({ phases, powerMin, powerMax }: Props) {
  const chartColors = useChartColors();
  const totalMin = phases.reduce((s, p) => s + p.duration_min, 0);

  if (totalMin <= 0 || phases.length === 0) return null;

  const colorMap: Record<Intensity, string> = {
    rest: `${chartColors.tick}40`,
    easy: `${chartColors.fitness}50`,
    moderate: `${chartColors.form}60`,
    hard: `${chartColors.threshold}70`,
    very_hard: `${chartColors.fitness}90`,
  };

  return (
    <div className="my-3">
      {/* Power annotation */}
      {powerMin != null && powerMax != null && (
        <div className="flex justify-center mb-1.5">
          <span className="text-[10px] font-data text-muted-foreground">
            Target: {powerMin}{'\u2013'}{powerMax} W
          </span>
        </div>
      )}

      {/* Timeline bar */}
      <div className="flex items-end gap-px rounded-lg overflow-hidden" style={{ height: 44 }}>
        {phases.map((phase, i) => {
          const widthPct = (phase.duration_min / totalMin) * 100;
          const showLabel = widthPct > 12;
          const showDuration = widthPct > 18;

          return (
            <div
              key={i}
              className={`relative flex flex-col items-center justify-end ${INTENSITY_HEIGHT[phase.intensity]} transition-all`}
              style={{
                width: `${widthPct}%`,
                backgroundColor: colorMap[phase.intensity],
                borderRadius: i === 0 ? '6px 0 0 6px' : i === phases.length - 1 ? '0 6px 6px 0' : undefined,
                minWidth: 4,
              }}
              title={`${phase.label}: ${phase.duration_min}min`}
            >
              {showLabel && (
                <span className="text-[8px] font-semibold uppercase tracking-wider text-foreground/70 leading-none">
                  {phase.label}
                </span>
              )}
              {showDuration && (
                <span className="text-[8px] font-data text-foreground/50 leading-none mt-0.5">
                  {phase.duration_min}m
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Duration label */}
      <div className="flex justify-between mt-1">
        <span className="text-[9px] text-muted-foreground font-data">0</span>
        <span className="text-[9px] text-muted-foreground font-data">{totalMin} min</span>
      </div>
    </div>
  );
}
