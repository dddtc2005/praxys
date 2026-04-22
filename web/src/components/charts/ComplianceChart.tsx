import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Cell,
} from 'recharts';
import type { WeeklyReview } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useChartColors } from '@/hooks/useChartColors';
import { Trans, useLingui } from '@lingui/react/macro';

interface Props {
  data: WeeklyReview;
  loadLabel?: string;
}

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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <Trans>Weekly Load Compliance</Trans>
        </CardTitle>
        {data.planned_estimated && (
          <p className="text-[11px] text-muted-foreground mt-1">
            <Trans>
              Planned bars are estimated — your plan has no {label} targets
              for the current training base.
            </Trans>
          </p>
        )}
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }} barGap={-30}>
            <defs>
              <pattern id="planned-pattern" patternUnits="userSpaceOnUse" width="6" height="6">
                <path d="M0 6L6 0" stroke={chartColors.tick} strokeWidth="1" strokeOpacity="0.4" />
              </pattern>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
            <XAxis
              dataKey="week"
              tick={{ fill: chartColors.tickLight, fontSize: 11 }}
              tickFormatter={(v: string) => v.slice(5)}
            />
            <YAxis tick={{ fill: chartColors.tickLight, fontSize: 11 }} />
            <Tooltip
              contentStyle={{
                backgroundColor: chartColors.tooltipBg,
                border: `1px solid ${chartColors.tooltipBorder}`,
                borderRadius: 8,
              }}
              labelStyle={{ color: chartColors.tickLight }}
              formatter={(value, name) => {
                return [Math.round(Number(value)), String(name)];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: chartColors.tickLight }} />
            {/* Planned bar — wider, behind, with diagonal pattern fill */}
            <Bar
              dataKey="planned"
              name={`${t`Planned`} ${label}`}
              fill="url(#planned-pattern)"
              stroke={chartColors.tick}
              strokeWidth={1}
              strokeOpacity={0.3}
              radius={[3, 3, 0, 0]}
              barSize={32}
            />
            {/* Actual bar — narrower, in front, solid fill with compliance coloring */}
            <Bar
              dataKey="actual"
              name={`${t`Actual`} ${label}`}
              radius={[3, 3, 0, 0]}
              barSize={22}
            >
              {chartData.map((entry, i) => {
                const pct = entry.compliance;
                let fill = chartColors.fitness; // green = on target
                if (pct != null) {
                  if (pct < 80) fill = chartColors.warning; // amber = under
                  else if (pct > 120) fill = chartColors.negative; // red = over
                }
                return <Cell key={i} fill={fill} fillOpacity={0.85} />;
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
