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
 *   state. A neutral mono percentage above each bar reports the ratio
 *   without turning it into a quality or safety verdict.
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
    const estimated = Boolean(
      data.week_actual_estimated[i] || data.week_planned_estimated[i],
    );
    return { week, planned, actual, compliance, estimated };
  });

  // RSS = Running Stress Score, the load metric Praxys uses when no
  // power-band targets exist. Inline-expand on first appearance per
  // the design system's "right word, explained inline once" rule.
  const labelExpansion = label === 'RSS'
    ? <Trans>load (Running Stress Score)</Trans>
    : <Trans>load ({label})</Trans>;

  // Compliance is descriptive actual/planned load, not a physiological score.
  const ComplianceLabel = (props: BarLabelProps) => {
    const { x, y, width, index } = props;
    if (index == null || x == null || y == null || width == null) return null;
    const entry = chartData[index];
    const pct = entry?.compliance;
    if (pct == null) return null;

    return (
      <text
        x={x + width / 2}
        y={y - 6}
        fill={chartColors.tickLight}
        fontSize={10}
        fontFamily="var(--font-mono)"
        textAnchor="middle"
        fontWeight={600}
      >
        {entry.estimated ? `~${pct}%` : `${pct}%`}
      </text>
    );
  };

  return (
    <section>
      <div className="flex flex-row items-baseline justify-between mb-4">
        {/* Tab label above already says "Load compliance" — keep just
            the unit hint here (e.g. "Running Stress Score"). */}
        <p className="text-[11px] text-muted-foreground">
          {labelExpansion}
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

      {(data.actual_estimated || data.planned_estimated) && (
        <p className="text-[11px] text-muted-foreground mb-2">
          <Trans>
            Bars marked with ~ use estimated load because selected-base activity
            or plan inputs are incomplete. Estimated weeks remain visible but are
            excluded from the summary.
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
        text={t`Compliance is the mean weekly actual-to-planned load ratio across completed weeks where actual and planned load both use exact selected-base inputs and the plan target is positive. Estimated weeks stay in the chart but are excluded from the summary. This is an execution comparison, not a quality, safety, recovery, or readiness score.`}
      />
    </section>
  );
}
