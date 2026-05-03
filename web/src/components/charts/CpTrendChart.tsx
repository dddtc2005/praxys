import { useState } from 'react';
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
import { useChartColors } from '@/hooks/useChartColors';
import { formatPace } from '@/lib/format';
import { Trans, useLingui } from '@lingui/react/macro';
import { tDisplay } from '@/lib/display-labels';

interface Props {
  data: CpTrendChartData;
  targetCp?: number | null;
  label?: string;
  unit?: string;
  metricName?: string;
}

type Range = '3m' | '6m' | '1y' | 'all';

const RANGE_DAYS: Record<Range, number | null> = {
  '3m': 90,
  '6m': 180,
  '1y': 365,
  all: null,
};

export default function CpTrendChart({ data, targetCp, label, unit = 'W', metricName = 'CP' }: Props) {
  const chartColors = useChartColors();
  const { t, i18n } = useLingui();
  const isPace = unit === '/km';
  const [range, setRange] = useState<Range>('6m');

  const allRows = data.dates.map((date, i) => ({ date, cp: data.values[i] }));
  const cutoff = (() => {
    const days = RANGE_DAYS[range];
    if (days == null || allRows.length === 0) return null;
    const last = new Date(allRows[allRows.length - 1].date);
    const c = new Date(last);
    c.setDate(c.getDate() - days);
    return c.toISOString().slice(0, 10);
  })();
  const chartData = cutoff ? allRows.filter((r) => r.date >= cutoff) : allRows;
  const formatValue = (v: number) => (isPace ? `${formatPace(v)}${unit}` : `${v}${unit}`);

  const RANGES: { key: Range; labelNode: React.ReactNode }[] = [
    { key: '3m', labelNode: <Trans>3M</Trans> },
    { key: '6m', labelNode: <Trans>6M</Trans> },
    { key: '1y', labelNode: <Trans>1Y</Trans> },
    { key: 'all', labelNode: <Trans>All</Trans> },
  ];

  const chartTitle = label ? tDisplay(label, i18n) : t`CP Trend`;
  const reducedMotion = typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  return (
    <section className="cp-trend" aria-label={chartTitle}>
      <div className="cp-trend-header">
        <span className="cp-trend-title">{chartTitle}</span>
        <div className="cp-trend-ranges" role="tablist" aria-label={t`Time range`}>
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              role="tab"
              aria-selected={range === r.key}
              className={`cp-trend-range ${range === r.key ? 'is-active' : ''}`.trim()}
              onClick={() => setRange(r.key)}
            >
              {r.labelNode}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 8, right: 10, left: 0, bottom: 5 }}>
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
            formatter={(value, name) => [formatValue(value as number), name as string]}
          />
          {targetCp != null && (
            <Line
              type="monotone"
              dataKey={() => targetCp}
              stroke={chartColors.tickLight}
              strokeWidth={1}
              strokeDasharray="6 4"
              dot={false}
              isAnimationActive={false}
              name={t`Target ${metricName}`}
            />
          )}
          <Line
            type="monotone"
            dataKey="cp"
            stroke={chartColors.threshold}
            strokeWidth={2}
            dot={{ fill: chartColors.threshold, r: 3 }}
            isAnimationActive={!reducedMotion}
            name={t`Current ${metricName}`}
          />
        </LineChart>
      </ResponsiveContainer>
    </section>
  );
}
