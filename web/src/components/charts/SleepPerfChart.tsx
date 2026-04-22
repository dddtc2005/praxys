import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useChartColors } from '@/hooks/useChartColors';
import { formatPace } from '@/lib/format';
import type { SleepPerfData } from '@/types/api';
import { Trans, useLingui } from '@lingui/react/macro';

interface Props {
  data: SleepPerfData;
}

export default function SleepPerfChart({ data }: Props) {
  const chartColors = useChartColors();
  const { t } = useLingui();
  const pairs = data?.pairs ?? [];
  const unit = data?.metric_unit ?? 'W';
  const metricLabel = data?.metric_label ?? 'Avg Power';
  const isPace = unit === 'sec/km';
  const chartData = pairs.map(([sleep, metric]) => ({ sleep, metric }));
  const yLabel = `${metricLabel} (${unit})`;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <Trans>Sleep Score vs {metricLabel}</Trans>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <ScatterChart margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
            <XAxis
              dataKey="sleep"
              name={t`Sleep Score`}
              tick={{ fill: chartColors.tickLight, fontSize: 11 }}
              type="number"
              label={{ value: t`Sleep Score`, position: 'insideBottom', offset: -2, fill: chartColors.tickLight, fontSize: 11 }}
            />
            <YAxis
              dataKey="metric"
              name={yLabel}
              tick={{ fill: chartColors.tickLight, fontSize: 11 }}
              type="number"
              tickFormatter={isPace ? (v: number) => formatPace(v) : undefined}
              label={{ value: yLabel, angle: -90, position: 'insideLeft', fill: chartColors.tickLight, fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: chartColors.tooltipBg,
                border: `1px solid ${chartColors.tooltipBorder}`,
                borderRadius: 8,
              }}
              labelStyle={{ color: chartColors.tickLight }}
              formatter={(value, _name, item) => {
                // When both axes set a `name` prop, recharts passes the
                // axis name into the formatter for every tooltip row, so
                // keying on `name` collapses both rows to the same label.
                // The payload item's `dataKey` is the stable identifier.
                const key =
                  (item as { dataKey?: string } | undefined)?.dataKey;
                if (key === 'metric') {
                  const display = isPace
                    ? formatPace(Number(value))
                    : `${value}${unit}`;
                  return [display, metricLabel];
                }
                return [value, t`Sleep Score`];
              }}
            />
            <Scatter data={chartData} fill={chartColors.projection} />
          </ScatterChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
