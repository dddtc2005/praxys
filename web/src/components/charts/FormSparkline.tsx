import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
  Tooltip,
  XAxis,
} from 'recharts';
import type { TsbSparkline } from '@/types/api';
import { useScience, tsbZoneFromConfig } from '@/contexts/ScienceContext';

interface Props {
  data: TsbSparkline;
}

function SparkTooltip({ active, payload, label, tsbZones }: any) {
  if (!active || !payload?.length) return null;
  const entry = payload[0]?.payload;
  const val = entry?.tsb ?? entry?.proj ?? 0;
  const isProj = entry?._projected;
  const zone = tsbZoneFromConfig(val, tsbZones ?? []);
  return (
    <div className="rounded-md border border-border bg-card px-2.5 py-1.5 shadow-lg shadow-black/30">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-muted-foreground font-data">{label}</span>
        {isProj && (
          <span className="text-[8px] uppercase tracking-wider text-accent-purple font-semibold">
            Proj
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-1.5 mt-0.5">
        <span className="text-sm font-bold font-data" style={{ color: zone.color }}>
          {val.toFixed(1)}
        </span>
        <span className="text-[9px] uppercase tracking-wider" style={{ color: zone.color, opacity: 0.7 }}>
          {zone.label}
        </span>
      </div>
    </div>
  );
}

export default function FormSparkline({ data }: Props) {
  const { tsbZones } = useScience();
  const { chartData, yMin, yMax, hasProjection, latestTsb } = useMemo(() => {
    const hasProjData = !!(data.projected_dates?.length && data.projected_values?.length);

    const historical = data.dates.map((d, i) => {
      const isLast = hasProjData && i === data.dates.length - 1;
      return {
        date: d,
        tsb: data.values[i],
        // Bridge: last historical point also gets proj value so lines connect
        proj: isLast ? data.values[i] : null as number | null,
        _projected: false,
      };
    });

    const projRows: typeof historical = [];
    if (hasProjData) {
      for (let i = 0; i < data.projected_dates!.length; i++) {
        projRows.push({
          date: data.projected_dates![i],
          tsb: null as any,
          proj: data.projected_values![i],
          _projected: true,
        });
      }
    }

    const merged = [...historical, ...projRows];

    const allVals = [...data.values, ...(data.projected_values ?? [])];
    const min = Math.min(...allVals);
    const max = Math.max(...allVals);
    const latest = data.values[data.values.length - 1] ?? 0;

    return {
      chartData: merged,
      yMin: Math.min(min, -10) - 5,
      yMax: Math.max(max, 10) + 5,
      hasProjection: hasProjData,
      latestTsb: latest,
    };
  }, [data]);

  const zone = tsbZoneFromConfig(latestTsb, tsbZones);

  return (
    <div className="rounded-2xl bg-card p-5 sm:p-6">
      {/* Header with current value */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Form (TSB)
        </h3>
        <div className="flex items-center gap-2">
          <span
            className="text-lg font-bold font-data"
            style={{ color: zone.color }}
          >
            {latestTsb.toFixed(1)}
          </span>
          <span
            className="text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
            style={{
              color: zone.color,
              backgroundColor: `${zone.color}15`,
            }}
          >
            {zone.label}
          </span>
        </div>
      </div>

      <div style={{ width: '100%', height: 200 }}>
        <ResponsiveContainer>
          <AreaChart data={chartData} margin={{ top: 5, right: 5, bottom: 0, left: 5 }}>
            <defs>
              <linearGradient id="sparkGreen" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#00ff87" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#00ff87" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="sparkRed" x1="0" y1="1" x2="0" y2="0">
                <stop offset="0%" stopColor="#ef4444" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="sparkProj" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.2} />
                <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
              </linearGradient>
            </defs>

            {/* Zone bands (from science context) */}
            {tsbZones.map((zone) => (
              <ReferenceArea
                key={zone.label}
                y1={Math.max(zone.min ?? -100, yMin)}
                y2={Math.min(zone.max ?? 100, yMax)}
                fill={zone.color}
                fillOpacity={0.03}
                ifOverflow="hidden"
              />
            ))}

            <XAxis
              dataKey="date"
              tick={{ fontSize: 9, fill: '#475569', fontFamily: 'JetBrains Mono, monospace' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: string) => {
                const d = new Date(v);
                return `${d.getMonth() + 1}/${d.getDate()}`;
              }}
            />
            <Tooltip content={<SparkTooltip tsbZones={tsbZones} />} />

            {/* Zone boundary lines */}
            <ReferenceLine y={0} stroke="#475569" strokeWidth={1} strokeDasharray="4 3" />
            {tsbZones.map((zone) =>
              zone.min != null && zone.min !== 0 ? (
                <ReferenceLine
                  key={`line-${zone.min}`}
                  y={zone.min}
                  stroke={zone.color}
                  strokeWidth={0.5}
                  strokeOpacity={0.2}
                  strokeDasharray="2 4"
                />
              ) : null
            )}

            {/* Historical TSB area — positive */}
            <Area
              type="monotone"
              dataKey="tsb"
              stroke="#00ff87"
              strokeWidth={2}
              fill="url(#sparkGreen)"
              baseValue={0}
              connectNulls={false}
              isAnimationActive={false}
            />

            {/* Projected TSB */}
            {hasProjection && (
              <Area
                type="monotone"
                dataKey="proj"
                stroke="#8b5cf6"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                fill="url(#sparkProj)"
                baseValue={0}
                connectNulls={false}
                isAnimationActive={false}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Footer: timeframe + projection note */}
      <div className="flex items-center justify-between mt-2">
        <span className="text-[10px] text-muted-foreground">Last 14 days</span>
        {hasProjection && (
          <span className="text-[10px] text-accent-purple/60">
            + {data.projected_dates?.length ?? 0}d projected from plan
          </span>
        )}
      </div>
    </div>
  );
}
