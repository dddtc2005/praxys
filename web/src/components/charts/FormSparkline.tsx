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
import type { TsbSparkline, ScienceNoteInfo } from '@/types/api';
import { useScience, tsbZoneFromConfig } from '@/contexts/ScienceContext';
import ZoneLegend from '@/components/charts/ZoneLegend';
import ScienceNote from '@/components/ScienceNote';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useChartColors } from '@/hooks/useChartColors';
import { Trans, useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';

// Zone insights are keyed by the stable English `key` from the science
// label set, so the lookup survives label localization. When `key` is
// missing we fall back to `label`: lossless for en (key === label in
// English), silent miss for zh (translated label won't match any key).
const ZONE_INSIGHTS: Record<string, MessageDescriptor> = {
  Performance: msg`Freshened up — good window for racing or testing.`,
  Optimal: msg`Good balance of fitness and recovery. Ready for quality work.`,
  Productive: msg`Building fitness with manageable fatigue.`,
  'Productive & Maintenance': msg`Absorbing training while maintaining fitness.`,
  Cautionary: msg`Fatigue is climbing — watch recovery before adding load.`,
  Overreaching: msg`High fatigue accumulation. Prioritize recovery.`,
  Detraining: msg`Extended rest period. Fitness declining.`,
};

interface Props {
  data: TsbSparkline;
  scienceNote?: ScienceNoteInfo;
}

function SparkTooltip({ active, payload, label, tsbZones }: any) {
  if (!active || !payload?.length) return null;
  const entry = payload[0]?.payload;
  const val = entry?.tsb ?? entry?.proj ?? 0;
  const isProj = entry?._projected;
  const zone = tsbZoneFromConfig(val, tsbZones ?? []);
  return (
    <div className="rounded-lg border border-border bg-popover px-2.5 py-1.5 shadow-xl shadow-black/30">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-muted-foreground font-data">{label}</span>
        {isProj && (
          <span className="text-[8px] uppercase tracking-wider text-accent-purple font-semibold">
            <Trans>Proj</Trans>
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

export default function FormSparkline({ data, scienceNote }: Props) {
  const chartColors = useChartColors();
  const { tsbZones } = useScience();
  const { i18n } = useLingui();
  const { chartData, yMin, yMax, hasProjection, latestTsb } = useMemo(() => {
    const hasProjData = !!(data.projected_dates?.length && data.projected_values?.length);

    const historical = data.dates.map((d, i) => {
      const isLast = hasProjData && i === data.dates.length - 1;
      return {
        date: d,
        tsb: data.values[i],
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
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <Trans>Form (TSB)</Trans>
        </CardTitle>
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
      </CardHeader>
      <CardContent>
        <div style={{ width: '100%', height: 200 }}>
          <ResponsiveContainer>
            <AreaChart data={chartData} margin={{ top: 5, right: 5, bottom: 0, left: 5 }}>
              <defs>
                <linearGradient id="sparkGreen" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.fitness} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={chartColors.fitness} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="sparkRed" x1="0" y1="1" x2="0" y2="0">
                  <stop offset="0%" stopColor={chartColors.fatigue} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={chartColors.fatigue} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="sparkProj" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.projection} stopOpacity={0.2} />
                  <stop offset="100%" stopColor={chartColors.projection} stopOpacity={0} />
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
                tick={{ fontSize: 9, fill: chartColors.tick, fontFamily: 'JetBrains Mono Variable, monospace' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: string) => {
                  const d = new Date(v);
                  return `${d.getMonth() + 1}/${d.getDate()}`;
                }}
              />
              <Tooltip content={<SparkTooltip tsbZones={tsbZones} />} />

              {/* Zone boundary lines */}
              <ReferenceLine y={0} stroke={chartColors.tick} strokeWidth={1} strokeDasharray="4 3" />
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
                stroke={chartColors.form}
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
                  stroke={chartColors.projection}
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
          <span className="text-[10px] text-muted-foreground"><Trans>Last 14 days</Trans></span>
          {hasProjection && (
            <span className="text-[10px] text-accent-purple/60">
              <Trans>+ {data.projected_dates?.length ?? 0}d projected from plan</Trans>
            </span>
          )}
        </div>

        {/* Form insight — prefer the stable `key`, fall back to the
            English `label` so en-locale data without `key` still renders. */}
        {(() => {
          const insight =
            (zone.key && ZONE_INSIGHTS[zone.key]) ||
            ZONE_INSIGHTS[zone.label];
          if (!insight) return null;
          return (
            <p className="text-xs text-muted-foreground mt-3" style={{ color: `${zone.color}99` }}>
              {i18n._(insight)}
            </p>
          );
        })()}

        <ZoneLegend zones={tsbZones} />

        <ScienceNote
          text={scienceNote?.description || "Form (TSB) = Fitness (CTL) − Fatigue (ATL). Positive TSB means you're fresh; negative means fatigued."}
          sourceUrl={scienceNote?.citations?.[0]?.url}
          sourceLabel={scienceNote?.citations?.[0]?.label || scienceNote?.name}
        />
      </CardContent>
    </Card>
  );
}
