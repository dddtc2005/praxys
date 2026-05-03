import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
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
  ReferenceDot,
} from 'recharts';
import type { TimeSeriesData, WorkoutFlag } from '@/types/api';
import ScienceNote from '@/components/ScienceNote';
import ZoneLegend from '@/components/charts/ZoneLegend';
import { useScience, tsbZoneFromConfig } from '@/contexts/ScienceContext';
import { useChartColors } from '@/hooks/useChartColors';
import { Trans, useLingui } from '@lingui/react/macro';

import type { ScienceNoteInfo } from '@/types/api';

interface Props {
  data: TimeSeriesData;
  scienceNote?: ScienceNoteInfo;
  /** Flagged workouts (good / bad). Rendered as small dots above the
   *  bottom axis, clickable to drill through to /activities. Optional. */
  workoutFlags?: WorkoutFlag[];
}

const ZONE_OPACITIES = [0.04, 0.07, 0.06, 0.04, 0.05];

function CustomTooltip({ active, payload, label, tsbZones, chartColors }: any) {
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
          <span className="text-[9px] uppercase tracking-wider text-accent-cobalt font-semibold px-1.5 py-0.5 rounded bg-accent-cobalt/10">
            <Trans>Projected</Trans>
          </span>
        )}
      </div>
      <div className="space-y-1 text-[12px] font-data">
        {ctl && (
          <div className="flex justify-between gap-6">
            <span className="text-muted-foreground"><Trans>Fitness</Trans></span>
            <span style={{ color: chartColors.fitness }}>{ctl.value?.toFixed(1)}</span>
          </div>
        )}
        {atl && (
          <div className="flex justify-between gap-6">
            <span className="text-muted-foreground"><Trans>Fatigue</Trans></span>
            <span style={{ color: chartColors.fatigue }}>{atl.value?.toFixed(1)}</span>
          </div>
        )}
        {tsb && (
          <div className="flex justify-between gap-6 pt-1 border-t border-border">
            <span className="text-muted-foreground"><Trans>Form</Trans></span>
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

export default function FitnessFatigueChart({ data, scienceNote, workoutFlags }: Props) {
  const chartColors = useChartColors();
  const { t } = useLingui();
  const { tsbZones } = useScience();
  const navigate = useNavigate();
  // Limit overlay dots to dates actually rendered on the chart so a
  // "bad" flag from before the visible window doesn't render off-axis.
  const visibleDates = useMemo(() => new Set(data.dates), [data.dates]);
  const flags = useMemo(
    () => (workoutFlags ?? []).filter((f) => visibleDates.has(f.date)),
    [workoutFlags, visibleDates],
  );
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
    ].filter((v) => Number.isFinite(v));
    const min = allVals.length > 0 ? Math.min(...allVals) : -20;
    const max = allVals.length > 0 ? Math.max(...allVals) : 80;

    return {
      chartData: deduped,
      yMin: Math.floor(min / 10) * 10 - 10,
      yMax: Math.ceil(max / 10) * 10 + 10,
      hasProjection: hasProjData,
    };
  }, [data]);

  const projectionStartDate = data.dates[data.dates.length - 1];

  return (
    // Borderless content block (no Card chrome) — used inside the
    // Diagnosis chart switcher tab. Section identity comes from the
    // switcher tab label above; no own header eyebrow needed.
    <section>
      <div className="flex flex-row items-center justify-between mb-4">
        <p className="text-[10px] font-data uppercase tracking-[0.14em] text-muted-foreground">
          <Trans>Fitness / Fatigue / Form</Trans>
        </p>
        {/* Legend pairs each acronym with its plain-English meaning.
            Power users keep CTL/ATL/TSB anchors; first-timers get
            meaning. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5 rounded-full" style={{ backgroundColor: chartColors.fitness }} />
            <span className="text-muted-foreground"><Trans>Fitness</Trans> <span className="font-data">CTL</span></span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5 rounded-full" style={{ backgroundColor: chartColors.fatigue }} />
            <span className="text-muted-foreground"><Trans>Fatigue</Trans> <span className="font-data">ATL</span></span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5 rounded-full" style={{ backgroundColor: chartColors.form }} />
            <span className="text-muted-foreground"><Trans>Form</Trans> <span className="font-data">TSB</span></span>
          </span>
          {hasProjection && (
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 rounded-full opacity-60" style={{ backgroundColor: chartColors.projection, borderTop: `2px dashed ${chartColors.projection}` }} />
              <span className="text-muted-foreground"><Trans>Projected</Trans></span>
            </span>
          )}
        </div>
      </div>
      <div>
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
                label={{ value: t`Today`, position: 'top', fill: chartColors.projection, fontSize: 10 }}
              />
            )}

            <XAxis
              dataKey="date"
              tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono Variable, monospace' }}
              tickLine={false}
              axisLine={{ stroke: chartColors.grid }}
              tickFormatter={(v: string) => {
                const d = new Date(v);
                return `${d.getMonth() + 1}/${d.getDate()}`;
              }}
              interval={Math.max(0, Math.floor(chartData.length / 10) - 1)}
            />
            <YAxis
              tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono Variable, monospace' }}
              tickLine={false}
              axisLine={false}
              domain={[yMin, yMax]}
            />
            <Tooltip content={<CustomTooltip tsbZones={tsbZones} chartColors={chartColors} />} />

            <Area type="monotone" dataKey="tsb" fill="url(#tsbAreaGrad)" stroke="none" connectNulls={false} isAnimationActive={false} />

            <Line type="monotone" dataKey="ctl" stroke={chartColors.fitness} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} name={t`CTL (Fitness)`} />
            <Line type="monotone" dataKey="atl" stroke={chartColors.fatigue} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} name={t`ATL (Fatigue)`} />
            <Line type="monotone" dataKey="tsb" stroke={chartColors.form} strokeWidth={2.5} dot={false} connectNulls={false} isAnimationActive={false} name={t`TSB (Form)`} />

            {hasProjection && (
              <>
                <Area type="monotone" dataKey="proj_tsb" fill="url(#projAreaGrad)" stroke="none" connectNulls={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="proj_ctl" stroke={chartColors.fitness} strokeWidth={1.5} strokeDasharray="6 4" strokeOpacity={0.5} dot={false} connectNulls={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="proj_atl" stroke={chartColors.fatigue} strokeWidth={1.5} strokeDasharray="6 4" strokeOpacity={0.5} dot={false} connectNulls={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="proj_tsb" stroke={chartColors.projection} strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} />
              </>
            )}

            {flags.map((flag) => {
              const tooltipText = `${flag.type === 'good' ? t`Good workout` : t`Bad workout`} \u00b7 ${flag.date}${flag.description ? `\n${flag.description}` : ''}`;
              return (
                <ReferenceDot
                  key={`${flag.type}-${flag.date}`}
                  x={flag.date}
                  /* Sit ~6% above the chart floor so dots land on the
                     visible plot area instead of crowding axis ticks. */
                  y={yMin + (yMax - yMin) * 0.06}
                  r={4}
                  fill={flag.type === 'good' ? 'var(--primary)' : 'var(--destructive)'}
                  stroke="var(--card)"
                  strokeWidth={1.5}
                  ifOverflow="hidden"
                  shape={(props) => {
                    const { cx, cy, fill, stroke, strokeWidth, r } = props as { cx: number; cy: number; fill: string; stroke: string; strokeWidth: number; r: number };
                    return (
                      <g
                        style={{ cursor: 'pointer' }}
                        onClick={() => navigate('/activities')}
                        role="button"
                        aria-label={tooltipText}
                      >
                        <circle cx={cx} cy={cy} r={r} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
                        {/* Larger transparent hit target so the small
                            visual dot doesn't require pixel-precise aim. */}
                        <circle cx={cx} cy={cy} r={r + 4} fill="transparent" />
                        <title>{tooltipText}</title>
                      </g>
                    );
                  }}
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>

        {flags.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px]">
            <span className="font-data uppercase tracking-wider text-muted-foreground">
              <Trans>Flagged</Trans>
            </span>
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
              <Trans>good \u00b7 {flags.filter((f) => f.type === 'good').length}</Trans>
            </span>
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-destructive" />
              <Trans>bad \u00b7 {flags.filter((f) => f.type === 'bad').length}</Trans>
            </span>
          </div>
        )}

        <ZoneLegend zones={tsbZones} />


        <ScienceNote
          text={scienceNote?.description || "Fitness (CTL) is an exponentially weighted moving average of daily training load. Fatigue (ATL) uses a shorter window. Form (TSB) = CTL \u2212 ATL."}
          sourceUrl={scienceNote?.citations?.[0]?.url || "https://help.trainingpeaks.com/hc/en-us/articles/204071944"}
          sourceLabel={scienceNote?.citations?.[0]?.label || "TrainingPeaks PMC"}
        />
      </div>
    </section>
  );
}
