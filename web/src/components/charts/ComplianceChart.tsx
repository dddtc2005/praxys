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

interface Props {
  data: WeeklyReview;
  loadLabel?: string;
}

export default function ComplianceChart({ data, loadLabel }: Props) {
  const chartData = data.weeks.map((week, i) => ({
    week,
    planned: data.planned_rss[i],
    actual: data.actual_rss[i],
  }));

  return (
    <div className="rounded-2xl bg-card p-5 sm:p-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
        Weekly Load Compliance
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="week"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickFormatter={(v: string) => v.slice(5)}
          />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 8,
            }}
            labelStyle={{ color: '#94a3b8' }}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, color: '#94a3b8' }}
          />
          <Bar dataKey="planned" name={`Planned ${loadLabel || 'RSS'}`} fill="#475569" radius={[3, 3, 0, 0]} />
          <Bar dataKey="actual" name={`Actual ${loadLabel || 'RSS'}`} fill="#3b82f6" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
