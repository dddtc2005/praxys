import type { DisplayConfig } from '@/types/api';

interface Props {
  distribution: { supra_cp: number; threshold: number; tempo: number; easy: number };
  display?: DisplayConfig;
}

const ZONE_COLORS = [
  { color: 'bg-destructive', textColor: 'text-destructive' },
  { color: 'bg-accent-amber', textColor: 'text-accent-amber' },
  { color: 'bg-accent-blue', textColor: 'text-accent-blue' },
  { color: 'bg-muted-foreground', textColor: 'text-muted-foreground' },
];

// Map distribution keys to ordered zone indices (highest intensity first)
const DIST_KEYS = ['supra_cp', 'threshold', 'tempo', 'easy'] as const;

export default function DistributionBar({ distribution, display }: Props) {
  const total = distribution.supra_cp + distribution.threshold + distribution.tempo + distribution.easy;

  // Use display config zone names if available (reversed: Z5→Z2 = highest→lowest)
  const zoneLabels = display?.zone_names
    ? [display.zone_names[4] || display.zone_names[3], display.zone_names[3] || 'Threshold', display.zone_names[2] || 'Tempo', display.zone_names[1] || 'Easy']
    : ['Supra-CP', 'Threshold', 'Tempo', 'Easy'];

  const zones = DIST_KEYS.map((key, i) => ({
    key,
    label: zoneLabels[i],
    ...ZONE_COLORS[i],
    pct: total > 0 ? (distribution[key] / total) * 100 : 0,
  }));

  return (
    <div>
      {/* Stacked bar */}
      <div className="flex h-6 w-full overflow-hidden rounded-full">
        {zones.map((zone) => {
          if (zone.pct === 0) return null;
          return (
            <div
              key={zone.key}
              className={`${zone.color} flex items-center justify-center text-[10px] font-semibold text-base`}
              style={{ width: `${zone.pct}%` }}
              title={`${zone.label}: ${zone.pct.toFixed(0)}%`}
            >
              {zone.pct >= 8 ? `${zone.pct.toFixed(0)}%` : ''}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        {zones.map((zone) => (
          <span key={zone.key} className="flex items-center gap-1.5">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${zone.color}`} />
            <span className="text-muted-foreground">{zone.label}</span>
            <span className={`font-data font-semibold ${zone.textColor}`}>{zone.pct.toFixed(0)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}
