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

interface Props {
  data: [number, number][];
}

export default function SleepPerfChart({ data }: Props) {
  const chartColors = useChartColors();
  const chartData = data.map(([sleep, power]) => ({
    sleep,
    power,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Sleep Score vs Power
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <ScatterChart margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
            <XAxis
              dataKey="sleep"
              name="Sleep Score"
              tick={{ fill: chartColors.tickLight, fontSize: 11 }}
              type="number"
              label={{ value: 'Sleep Score', position: 'insideBottom', offset: -2, fill: chartColors.tickLight, fontSize: 11 }}
            />
            <YAxis
              dataKey="power"
              name="Avg Power (W)"
              tick={{ fill: chartColors.tickLight, fontSize: 11 }}
              type="number"
              label={{ value: 'Avg Power (W)', angle: -90, position: 'insideLeft', fill: chartColors.tickLight, fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: chartColors.tooltipBg,
                border: `1px solid ${chartColors.tooltipBorder}`,
                borderRadius: 8,
              }}
              labelStyle={{ color: chartColors.tickLight }}
              formatter={(value, name) => [
                `${value}${name === 'power' ? 'W' : ''}`,
                name === 'power' ? 'Avg Power' : 'Sleep Score',
              ]}
            />
            <Scatter data={chartData} fill={chartColors.projection} />
          </ScatterChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
