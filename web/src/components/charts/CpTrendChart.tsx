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
    <div className="rounded-2xl bg-card p-5 sm:p-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
        {label || 'CP Trend'}
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="date"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickFormatter={(v: string) => v.slice(5)}
            interval={Math.max(0, Math.floor(chartData.length / 6) - 1)}
          />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            domain={['dataMin - 5', 'dataMax + 5']}
            tickFormatter={isPace ? (v: number) => formatPace(v) : undefined}
            reversed={isPace}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 8,
            }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(value) => [formatValue(value as number), metricName]}
          />
          {targetCp != null && (
            <Line
              type="monotone"
              dataKey={() => targetCp}
              stroke="#f59e0b"
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
            stroke="#f59e0b"
            strokeWidth={2}
            dot={{ fill: '#f59e0b', r: 3 }}
            name={metricName}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
