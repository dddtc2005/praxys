import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface Props {
  data: [number, number][];
}

export default function SleepPerfChart({ data }: Props) {
  const chartData = data.map(([sleep, power]) => ({
    sleep,
    power,
  }));

  return (
    <div className="rounded-2xl bg-card p-5 sm:p-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
        Sleep Score vs Power
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="sleep"
            name="Sleep Score"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            type="number"
            label={{ value: 'Sleep Score', position: 'insideBottom', offset: -2, fill: '#94a3b8', fontSize: 11 }}
          />
          <YAxis
            dataKey="power"
            name="Avg Power (W)"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            type="number"
            label={{ value: 'Avg Power (W)', angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 8,
            }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(value, name) => [
              `${value}${name === 'power' ? 'W' : ''}`,
              name === 'power' ? 'Avg Power' : 'Sleep Score',
            ]}
          />
          <Scatter data={chartData} fill="#a855f7" />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
