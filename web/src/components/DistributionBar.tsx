import type { ZoneDistribution } from '@/types/api';
import { useLingui } from '@lingui/react/macro';
import { tDisplay } from '@/lib/display-labels';

interface Props {
  distribution: ZoneDistribution[];
}

const ZONE_COLORS = [
  { color: 'bg-destructive', textColor: 'text-destructive' },
  { color: 'bg-accent-amber', textColor: 'text-accent-amber' },
  { color: 'bg-accent-blue', textColor: 'text-accent-blue' },
  { color: 'bg-accent-blue/50', textColor: 'text-accent-blue' },
  { color: 'bg-muted-foreground', textColor: 'text-muted-foreground' },
];

function getZoneColor(index: number, total: number) {
  const colorIdx = total - 1 - index;
  return ZONE_COLORS[Math.min(colorIdx, ZONE_COLORS.length - 1)] ?? ZONE_COLORS[ZONE_COLORS.length - 1];
}

export default function DistributionBar({ distribution }: Props) {
  const { i18n } = useLingui();
  const total = distribution.reduce((sum, d) => sum + d.actual_pct, 0);

  const zones = [...distribution].reverse().map((d, i) => ({
    name: tDisplay(d.name, i18n),
    pct: total > 0 ? d.actual_pct : 0,
    ...getZoneColor(distribution.length - 1 - i, distribution.length),
  }));

  return (
    <div>
      <div className="flex h-6 w-full overflow-hidden rounded-full">
        {zones.map((zone) => {
          if (zone.pct === 0) return null;
          return (
            <div
              key={zone.name}
              className={`${zone.color} flex items-center justify-center text-[10px] font-semibold text-base`}
              style={{ width: `${zone.pct}%` }}
              title={`${zone.name}: ${zone.pct}%`}
            >
              {zone.pct >= 8 ? `${zone.pct}%` : ''}
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        {zones.map((zone) => (
          <span key={zone.name} className="flex items-center gap-1.5">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${zone.color}`} />
            <span className="text-muted-foreground">{zone.name}</span>
            <span className={`font-data font-semibold ${zone.textColor}`}>{zone.pct}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}
