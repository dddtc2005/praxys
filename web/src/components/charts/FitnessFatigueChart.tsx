import { useMemo } from 'react';
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  ComposedChart,
  ReferenceArea,
  ReferenceLine,
} from 'recharts';
import type { TimeSeriesData, TsbZoneConfig } from '@/types/api';
import ScienceNote from '@/components/ScienceNote';
import { useScience, tsbZoneFromConfig } from '@/contexts/ScienceContext';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { chartColors } from '@/lib/chart-theme';

interface Props {
  data: TimeSeriesData;
}

const ZONE_OPACITIES = [0.04, 0.07, 0.06, 0.04, 0.05];

function CustomTooltip({ active, payload, label, tsbZones }: any) {
  if (!active || !payload?.length) return null;
  const isProjected = payload[0]?.payload?._projected;
  const ctl = payload.find((p: any) => p.dataKey === 'ctl' || p.dataKey === 'proj_ctl');
  const atl = payload.find((p: any) => p.dataKey === 'atl' || p.dataKey === 'proj_atl');
  const tsb = payload.find((p: any) => p.dataKey === 'tsb' || p.dataKey === 'proj_tsb');
  const tsbVal = tsb?.value ?? 0;
  const zone = tsbZoneFromConfig(tsbVal, tsbZones ?? []);

  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2.5 shadow-xl shadow-black/40">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[11px] text-muted-foreground font-data">{label}</span>
        {isProjected && (
          <span className="text-[9px] uppercase tracking-wider text-accent-purple font-semibold px-1.5 py-0.5 rounded bg-accent-purple/10">
            Projected
          </span>
        )}
      </div>
      <div className="space-y-1 text-[12px] font-data">
        {ctl && (
          <div className="flex justify-between gap-6">
            <span className="text-muted-foreground">Fitness</span>
            <span style={{ color: chartColors.fitness }}>{ctl.value?.toFixed(1)}</span>
          </div>
        )}
        {atl && (
          <div className="flex justify-between gap-6">
            <span className="text-muted-foreground">Fatigue</span>
            <span style={{ color: chartColors.fatigue }}>{atl.value?.toFixed(1)}</span>
          </div>
        )}
        {tsb && (
          <div className="flex justify-between gap-6 pt-1 border-t border-border">
            <span className="text-muted-foreground">Form</span>
            <span style={{ color: zone.color }} className="font-semibold">
              {tsbVal.toFixed(1)}
            </span>
          </div>
        )}
      </div>
      <div className="mt-2 pt-1.5 border-t border-border">
        <span
          className="text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: zone.color }}
        >
          {zone.label}
        </span>
      </div>
    </div>
  );
}

function ZoneLegend({ zones: tsbZones }: { zones: TsbZoneConfig[] }) {
  const zones = tsbZones
    .filter((z) => z.label !== 'Detraining')
    .map((z) => {
      const lo = z.min != null ? String(z.min) : '';
      const hi = z.max != null ? String(z.max) : '';
      const range = lo && hi ? `${lo}\u2013${hi}` : lo ? `${lo}+` : `<${hi}`;
      return { label: z.label, color: z.color, range };
    });
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3">
      {zones.map((z) => (
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

export default function FitnessFatigueChart({ data }: Props) {
  const { tsbZones } = useScience();
  const { chartData, yMin, yMax, hasProjection } = useMemo(() => {
    const hasProjData = !!(data.projected_dates?.length && data.projected_ctl?.length);

    type Row = {
      date: string;
      ctl: number | null;
      atl: number | null;
      tsb: number | null;
      proj_ctl: number | null;
      proj_atl: number | null;
      proj_tsb: number | null;
      _projected: boolean;
    };

    const rows: Row[] = data.dates.map((date, i) => {
      const isLast = hasProjData && i === data.dates.length - 1;
      return {
        date,
        ctl: data.ctl[i],
        atl: data.atl[i],
        tsb: data.tsb[i],
        proj_ctl: isLast ? data.ctl[i] : null,
        proj_atl: isLast ? data.atl[i] : null,
        proj_tsb: isLast ? data.tsb[i] : null,
        _projected: false,
      };
    });

    if (hasProjData) {
      for (let i = 0; i < data.projected_dates!.length; i++) {
        rows.push({
          date: data.projected_dates![i],
          ctl: null,
          atl: null,
          tsb: null,
          proj_ctl: data.projected_ctl![i],
          proj_atl: data.projected_atl?.[i] ?? 0,
          proj_tsb: data.projected_tsb?.[i] ?? 0,
          _projected: true,
        });
      }
    }

    const deduped = rows.filter((d, i, arr) => i === 0 || d.date !== arr[i - 1].date);

    const allVals = [
      ...data.ctl, ...data.atl, ...data.tsb,
      ...(data.projected_ctl ?? []),
      ...(data.projected_atl ?? []),
      ...(data.projected_tsb ?? []),
    ];
    const min = Math.min(...allVals);
    const max = Math.max(...allVals);

    return {
      chartData: deduped,
      yMin: Math.floor(min / 10) * 10 - 10,
      yMax: Math.ceil(max / 10) * 10 + 10,
      hasProjection: hasProjData,
    };
  }, [data]);

  const projectionStartDate = data.dates[data.dates.length - 1];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Fitness / Fatigue / Form
        </CardTitle>
        <div className="flex items-center gap-4 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5 rounded-full" style={{ backgroundColor: chartColors.fitness }} />
            <span className="text-muted-foreground">CTL</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5 rounded-full" style={{ backgroundColor: chartColors.fatigue }} />
            <span className="text-muted-foreground">ATL</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5 rounded-full" style={{ backgroundColor: chartColors.form }} />
            <span className="text-muted-foreground">TSB</span>
          </span>
          {hasProjection && (
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 rounded-full opacity-60" style={{ backgroundColor: chartColors.projection, borderTop: `2px dashed ${chartColors.projection}` }} />
              <span className="text-muted-foreground">Projected</span>
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={380}>
          <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -5, bottom: 5 }}>
            <defs>
              <linearGradient id="tsbAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={chartColors.form} stopOpacity={0.15} />
                <stop offset="50%" stopColor={chartColors.form} stopOpacity={0} />
                <stop offset="100%" stopColor={chartColors.form} stopOpacity={0.15} />
              </linearGradient>
              <linearGradient id="projAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={chartColors.projection} stopOpacity={0.1} />
                <stop offset="50%" stopColor={chartColors.projection} stopOpacity={0} />
                <stop offset="100%" stopColor={chartColors.projection} stopOpacity={0.1} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} vertical={false} />

            {tsbZones.map((zone, i) => (
              <ReferenceArea
                key={zone.label}
                y1={Math.max(zone.min ?? -100, yMin)}
                y2={Math.min(zone.max ?? 100, yMax)}
                fill={zone.color}
                fillOpacity={ZONE_OPACITIES[i] ?? 0.05}
                ifOverflow="hidden"
              />
            ))}

            <ReferenceLine y={0} stroke={chartColors.tick} strokeWidth={1} strokeDasharray="4 3" />

            {hasProjection && (
              <ReferenceLine
                x={projectionStartDate}
                stroke={chartColors.projection}
                strokeWidth={1}
                strokeDasharray="3 3"
                label={{ value: 'Today', position: 'top', fill: chartColors.projection, fontSize: 10 }}
              />
            )}

            <XAxis
              dataKey="date"
              tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}
              tickLine={false}
              axisLine={{ stroke: chartColors.grid }}
              tickFormatter={(v: string) => {
                const d = new Date(v);
                return `${d.getMonth() + 1}/${d.getDate()}`;
              }}
              interval={Math.max(0, Math.floor(chartData.length / 10) - 1)}
            />
            <YAxis
              tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}
              tickLine={false}
              axisLine={false}
              domain={[yMin, yMax]}
            />
            <Tooltip content={<CustomTooltip tsbZones={tsbZones} />} />

            <Area type="monotone" dataKey="tsb" fill="url(#tsbAreaGrad)" stroke="none" connectNulls={false} isAnimationActive={false} />

            <Line type="monotone" dataKey="ctl" stroke={chartColors.fitness} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} name="CTL (Fitness)" />
            <Line type="monotone" dataKey="atl" stroke={chartColors.fatigue} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} name="ATL (Fatigue)" />
            <Line type="monotone" dataKey="tsb" stroke={chartColors.form} strokeWidth={2.5} dot={false} connectNulls={false} isAnimationActive={false} name="TSB (Form)" />

            {hasProjection && (
              <>
                <Area type="monotone" dataKey="proj_tsb" fill="url(#projAreaGrad)" stroke="none" connectNulls={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="proj_ctl" stroke={chartColors.fitness} strokeWidth={1.5} strokeDasharray="6 4" strokeOpacity={0.5} dot={false} connectNulls={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="proj_atl" stroke={chartColors.fatigue} strokeWidth={1.5} strokeDasharray="6 4" strokeOpacity={0.5} dot={false} connectNulls={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="proj_tsb" stroke={chartColors.projection} strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} />
              </>
            )}
          </ComposedChart>
        </ResponsiveContainer>

        <ZoneLegend zones={tsbZones} />

        <ScienceNote
          text="Fitness (CTL) is an exponentially weighted moving average of daily training load over 42 days. Fatigue (ATL) uses a 7-day window. Form (TSB) = CTL \u2212 ATL. Zones aligned with Stryd RSB: Performance (5\u201325) for race readiness, Optimal (-10\u20135) the sweet spot between stress and recovery, Productive (-25\u2013-10) building fitness with manageable fatigue, Overreaching (<-25) signals recovery needed. Projected values are estimated from your training plan. Uses the standard PMC model (Banister, 1975) with \u03B1 = 1/\u03C4, matching TrainingPeaks, Stryd, and Intervals.icu."
          sourceUrl="https://help.trainingpeaks.com/hc/en-us/articles/204071944"
          sourceLabel="TrainingPeaks PMC"
        />
      </CardContent>
    </Card>
  );
}
