import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import type { WeeklyReview } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useChartColors } from '@/hooks/useChartColors';

interface Props {
  data: WeeklyReview;
  loadLabel?: string;
}

export default function ComplianceChart({ data, loadLabel }: Props) {
  const chartColors = useChartColors();
  const chartData = data.weeks.map((week, i) => ({
    week,
    planned: data.planned_rss[i],
    actual: data.actual_rss[i],
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Weekly Load Compliance
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
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
            />
            <Legend wrapperStyle={{ fontSize: 12, color: chartColors.tickLight }} />
            <Bar dataKey="planned" name={`Planned ${loadLabel || 'RSS'}`} fill={chartColors.tick} radius={[3, 3, 0, 0]} />
            <Bar dataKey="actual" name={`Actual ${loadLabel || 'RSS'}`} fill={chartColors.form} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
