import type { TsbZoneConfig } from '@/types/api';

interface Props {
  zones: TsbZoneConfig[];
}

export default function ZoneLegend({ zones }: Props) {
  const visible = zones
    .filter((z) => z.label !== 'Detraining')
    .map((z) => {
      const lo = z.min != null ? String(z.min) : '';
      const hi = z.max != null ? String(z.max) : '';
      const range = lo && hi ? `${lo}\u2013${hi}` : lo ? `${lo}+` : `<${hi}`;
      return { label: z.label, color: z.color, range };
    });

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3">
      {visible.map((z) => (
        <div key={z.label} className="flex items-center gap-1.5">
          <div
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: z.color, opacity: 0.8 }}
          />
          <span className="text-[10px] text-muted-foreground">
            {z.label} <span className="font-data opacity-60">{z.range}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
