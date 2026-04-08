import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { CpTrendChart as CpTrendChartData } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { chartColors } from '@/lib/chart-theme';

interface Props {
  data: CpTrendChartData;
  targetCp?: number | null;
  label?: string;
  unit?: string;
  metricName?: string;
}

function formatPace(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = Math.round(totalSec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export default function CpTrendChart({ data, targetCp, label, unit = 'W', metricName = 'CP' }: Props) {
  const isPace = unit === '/km';
  const chartData = data.dates.map((date, i) => ({
    date,
    cp: data.values[i],
  }));

  const formatValue = (v: number) => isPace ? `${formatPace(v)}${unit}` : `${v}${unit}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {label || 'CP Trend'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
            <XAxis
              dataKey="date"
              tick={{ fill: chartColors.tickLight, fontSize: 11 }}
              tickFormatter={(v: string) => v.slice(5)}
              interval={Math.max(0, Math.floor(chartData.length / 6) - 1)}
            />
            <YAxis
              tick={{ fill: chartColors.tickLight, fontSize: 11 }}
              domain={['dataMin - 5', 'dataMax + 5']}
              tickFormatter={isPace ? (v: number) => formatPace(v) : undefined}
              reversed={isPace}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: chartColors.tooltipBg,
                border: `1px solid ${chartColors.tooltipBorder}`,
                borderRadius: 8,
              }}
              labelStyle={{ color: chartColors.tickLight }}
              formatter={(value) => [formatValue(value as number), metricName]}
            />
            {targetCp != null && (
              <Line
                type="monotone"
                dataKey={() => targetCp}
                stroke={chartColors.threshold}
                strokeWidth={1}
                strokeDasharray="6 4"
                dot={false}
                isAnimationActive={false}
                name="Target"
              />
            )}
            <Line
              type="monotone"
              dataKey="cp"
              stroke={chartColors.threshold}
              strokeWidth={2}
              dot={{ fill: chartColors.threshold, r: 3 }}
              name={metricName}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
