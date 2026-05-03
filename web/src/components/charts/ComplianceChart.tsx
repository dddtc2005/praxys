import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LabelList,
} from 'recharts';
import type { WeeklyReview } from '@/types/api';
import { useChartColors } from '@/hooks/useChartColors';
import ScienceNote from '@/components/ScienceNote';
import { Trans, useLingui } from '@lingui/react/macro';

interface Props {
  data: WeeklyReview;
  loadLabel?: string;
}

interface BarLabelProps {
  x?: number;
  y?: number;
  width?: number;
  index?: number;
}

/**
 * Weekly load compliance — borderless content block (no Card chrome).
 * Used inside the Diagnosis chart switcher tab.
 *
 * Design choices:
 * - Single primary color for the actual bar regardless of compliance
 *   state. The under/on/over signal lives in a small mono % label
 *   above each bar (semantic color: amber under, primary on,
 *   destructive over). Replaces the prior cell-by-cell green/amber/red
 *   bar fill which broke the brand's restraint rule.
 * - Both bars same width (24px) with `barGap={-24}`, so they overlap
 *   concentrically around a shared x-center. Taller bar shows above
 *   the shorter; no off-center artifact.
 * - Planned bar is a muted ghost (no diagonal pattern, no border).
 *   Opacity contrast with the primary actual bar is the affordance.
 */
export default function ComplianceChart({ data, loadLabel }: Props) {
  const chartColors = useChartColors();
  const { t } = useLingui();
  const label = loadLabel || 'RSS';

  const chartData = data.weeks.map((week, i) => {
    const planned = data.planned_load[i] ?? 0;
    const actual = data.actual_load[i] ?? 0;
    const compliance = planned > 0 ? Math.round((actual / planned) * 100) : null;
    return { week, planned, actual, compliance };
  });

  // RSS = Running Stress Score, the load metric Praxys uses when no
  // power-band targets exist. Inline-expand on first appearance per
  // the design system's "right word, explained inline once" rule.
  const labelExpansion = label === 'RSS'
    ? <Trans>load (Running Stress Score)</Trans>
    : <Trans>load ({label})</Trans>;

  // Compliance % rendered above each actual bar. Single-color bars +
  // a small mono percentage with semantic color carry the
  // under/on/over signal — replaces the prior cell-coloring.
  const ComplianceLabel = (props: BarLabelProps) => {
    const { x, y, width, index } = props;
    if (index == null || x == null || y == null || width == null) return null;
    const entry = chartData[index];
    const pct = entry?.compliance;
    if (pct == null) return null;
    const color =
      pct < 80
        ? 'var(--accent-amber-val)'
        : pct > 120
          ? 'var(--destructive)'
          : 'var(--primary)';
    return (
      <text
        x={x + width / 2}
        y={y - 6}
        fill={color}
        fontSize={10}
        fontFamily="var(--font-mono)"
        textAnchor="middle"
        fontWeight={600}
      >
        {pct}%
      </text>
    );
  };

  return (
    <section>
      <div className="flex flex-row items-baseline justify-between mb-4">
        <p className="text-[10px] font-data uppercase tracking-[0.14em] text-muted-foreground">
          <Trans>Weekly Load Compliance</Trans>
          <span className="normal-case tracking-normal text-muted-foreground/70 ml-2">
            {labelExpansion}
          </span>
        </p>
        {/* Inline two-step legend replaces the prior Recharts Legend
            chrome; ghost bar + solid bar are the visual key, the
            labels describe what each represents. */}
        <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-2 rounded-sm bg-muted-foreground/25" />
            <Trans>Planned</Trans>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-2 rounded-sm bg-primary/85" />
            <Trans>Actual</Trans>
          </span>
        </div>
      </div>

      {data.planned_estimated && (
        <p className="text-[11px] text-muted-foreground mb-2">
          <Trans>
            Planned bars are estimated — your plan has no {label} targets
            for the current training base.
          </Trans>
        </p>
      )}

      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 18, right: 10, left: 0, bottom: 5 }} barGap={-24}>
          <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} vertical={false} />
          <XAxis
            dataKey="week"
            tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono Variable, monospace' }}
            tickLine={false}
            axisLine={{ stroke: chartColors.grid }}
            tickFormatter={(v: string) => v.slice(5)}
          />
          <YAxis
            tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono Variable, monospace' }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: chartColors.tooltipBg,
              border: `1px solid ${chartColors.tooltipBorder}`,
              borderRadius: 8,
            }}
            labelStyle={{ color: chartColors.tickLight }}
            formatter={(value, name) => [Math.round(Number(value)), String(name)]}
          />
          <Bar
            dataKey="planned"
            name={`${t`Planned`} ${label}`}
            fill="var(--muted-foreground)"
            fillOpacity={0.22}
            radius={[3, 3, 0, 0]}
            barSize={24}
          />
          <Bar
            dataKey="actual"
            name={`${t`Actual`} ${label}`}
            fill="var(--primary)"
            fillOpacity={0.85}
            radius={[3, 3, 0, 0]}
            barSize={24}
          >
            <LabelList dataKey="compliance" content={ComplianceLabel as never} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <ScienceNote
        text={t`Compliance compares the load you actually accumulated each week (Actual) against the load your plan called for (Planned). The percentage above each bar shows how close you came: green for 80–120% (on target), amber under 80%, red over 120%. The load metric (RSS or W-equivalent) is set by your training base.`}
      />
    </section>
  );
}
