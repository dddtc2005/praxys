import { msg } from '@lingui/core/macro';
import { Trans, useLingui } from '@lingui/react/macro';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import ScienceNote from '@/components/ScienceNote';
import { useChartColors } from '@/hooks/useChartColors';
import type { DiagnosisData } from '@/types/api';

const TREND_LABELS = {
  increasing: msg`Increasing`,
  decreasing: msg`Decreasing`,
  stable: msg`Stable`,
  insufficient_data: msg`Insufficient data`,
};

function formatWeekEnding(value: string, locale: string): string {
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(date);
}

/** Weekly distance history using the same non-overlapping buckets as diagnosis. */
export default function WeeklyVolumeChart({
  volume,
}: {
  volume: DiagnosisData['volume'];
}) {
  const chartColors = useChartColors();
  const { i18n, t } = useLingui();
  const locale = i18n.locale || 'en';
  const weeklyKm = volume.weekly_km ?? [];
  const chartData = (volume.weeks ?? []).map((week, index) => ({
    week,
    distance: weeklyKm[index] ?? 0,
  }));
  const trendMessage = TREND_LABELS[volume.trend as keyof typeof TREND_LABELS]
    ?? TREND_LABELS.insufficient_data;

  return (
    <section>
      <dl className="grid grid-cols-2 gap-4 rounded-lg bg-muted/35 p-4">
        <div>
          <dt className="text-xs text-muted-foreground"><Trans>Weekly average</Trans></dt>
          <dd className="mt-1 font-data text-lg font-semibold text-foreground">
            {volume.weekly_avg_km.toFixed(1)} <span className="text-xs font-normal text-muted-foreground">km</span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground"><Trans>Trend</Trans></dt>
          <dd className="mt-1 text-sm font-medium text-foreground">
            {i18n._(trendMessage)}
          </dd>
        </div>
      </dl>

      <div className="mt-5">
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={chartData} margin={{ top: 14, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} vertical={false} />
            <XAxis
              dataKey="week"
              tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono Variable, monospace' }}
              tickFormatter={(value: string) => formatWeekEnding(value, locale)}
              tickLine={false}
              axisLine={{ stroke: chartColors.grid }}
            />
            <YAxis
              tick={{ fill: chartColors.tick, fontSize: 10, fontFamily: 'JetBrains Mono Variable, monospace' }}
              tickLine={false}
              axisLine={false}
              width={42}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: chartColors.tooltipBg,
                border: `1px solid ${chartColors.tooltipBorder}`,
                borderRadius: 8,
              }}
              labelStyle={{ color: chartColors.tickLight }}
              labelFormatter={(value) => t`Week ending ${formatWeekEnding(String(value), locale)}`}
              formatter={(value) => [`${Number(value).toFixed(1)} km`, t`Distance`]}
            />
            <ReferenceLine
              y={volume.weekly_avg_km}
              stroke={chartColors.tickLight}
              strokeDasharray="4 3"
            />
            <Bar
              dataKey="distance"
              name={t`Distance`}
              fill="var(--primary)"
              fillOpacity={0.82}
              radius={[4, 4, 0, 0]}
              maxBarSize={54}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-5">
        <ScienceNote embedded>
          <p>
            <Trans>
              Each value is a non-overlapping seven-day bucket ending on the shown date. Weeks with no recorded distance remain in the series and average. Trend labels use a Praxys estimate: the newer half must differ from the older half by more than 10%; this is not a readiness score.
            </Trans>
          </p>
        </ScienceNote>
      </div>
    </section>
  );
}
