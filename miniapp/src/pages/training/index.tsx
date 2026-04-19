import { View, Text, Button } from '@tarojs/components';
import Taro, { usePullDownRefresh } from '@tarojs/taro';

import { useApi } from '@/hooks/useApi';
import type { TrainingResponse } from '@/types/api';
import LineChart from '@/components/LineChart';
import './index.scss';

/**
 * Training view — diagnosis summary, volume/consistency, and zone
 * distribution as a simple bar list. Recharts is React-DOM-only, so the
 * fitness-fatigue + CP trend charts will land in a follow-up when we
 * pick a Taro-compatible chart library.
 */
export default function TrainingPage() {
  const { data, loading, error, refetch } = useApi<TrainingResponse>('/api/training');
  usePullDownRefresh(() => {
    refetch();
    Taro.stopPullDownRefresh();
  });

  if (loading && !data) {
    return (
      <View className="train-root">
        <Text className="train-header">Training</Text>
        <View className="ts-card"><View className="ts-skeleton" /></View>
        <View className="ts-card"><View className="ts-skeleton" /></View>
      </View>
    );
  }

  if (error) {
    return (
      <View className="train-root">
        <Text className="train-header ts-destructive">Failed to load</Text>
        <Text>{error}</Text>
        <Button className="ts-button" onClick={() => refetch()}>Retry</Button>
      </View>
    );
  }

  if (!data) return null;

  const { diagnosis, cp_trend, fitness_fatigue } = data;
  const latestCp = cp_trend.values.length ? cp_trend.values[cp_trend.values.length - 1] : null;
  const hasFitnessFatigue = fitness_fatigue && fitness_fatigue.dates.length >= 2;
  const hasCpTrend = cp_trend && cp_trend.values.length >= 2;

  return (
    <View className="train-root">
      <Text className="train-header">Training</Text>

      <View className="ts-card">
        <Text className="ts-section-label">Volume</Text>
        <View className="train-hero">
          <Text className="train-hero-value ts-value">
            {diagnosis.volume.weekly_avg_km.toFixed(1)} km/week
          </Text>
          <Text className="train-hero-meta ts-muted">
            trend: {diagnosis.volume.trend}
          </Text>
        </View>
      </View>

      {latestCp != null && (
        <View className="ts-card">
          <Text className="ts-section-label">Critical Power</Text>
          <View className="train-hero">
            <Text className="train-hero-value ts-value">{latestCp.toFixed(0)} W</Text>
            <Text className="train-hero-meta ts-muted">
              latest estimate · {cp_trend.values.length} data points
            </Text>
          </View>
          {hasCpTrend && (
            <LineChart
              canvasId="train-cp-trend"
              height={220}
              showLegend={false}
              dates={cp_trend.dates}
              series={[
                { label: 'CP', color: '#44d08e', values: cp_trend.values, fill: true },
              ]}
            />
          )}
        </View>
      )}

      {hasFitnessFatigue && (
        <View className="ts-card">
          <Text className="ts-section-label">Fitness &amp; Fatigue</Text>
          <LineChart
            canvasId="train-ctl-atl-tsb"
            height={280}
            showZeroLine
            dates={fitness_fatigue.dates}
            series={[
              { label: 'Fitness (CTL)', color: '#44d08e', values: fitness_fatigue.ctl },
              { label: 'Fatigue (ATL)', color: '#ef4444', values: fitness_fatigue.atl },
              { label: 'Form (TSB)', color: '#3b82f6', values: fitness_fatigue.tsb },
            ]}
          />
        </View>
      )}

      <View className="ts-card">
        <Text className="ts-section-label">
          Zone distribution · {diagnosis.theory_name}
        </Text>
        {diagnosis.distribution.map((z) => (
          <ZoneBar
            key={z.name}
            name={z.name}
            actual={z.actual_pct}
            target={z.target_pct}
          />
        ))}
      </View>

      <View className="ts-card">
        <Text className="ts-section-label">Consistency</Text>
        <Text className="train-line">
          {diagnosis.consistency.total_sessions} sessions · gaps ≥7d:{' '}
          {diagnosis.consistency.weeks_with_gaps} · longest:{' '}
          {diagnosis.consistency.longest_gap_days}d
        </Text>
      </View>

      {diagnosis.diagnosis.length > 0 && (
        <View className="ts-card">
          <Text className="ts-section-label">Findings</Text>
          {diagnosis.diagnosis.map((f, i) => (
            <Text
              key={i}
              className={
                f.type === 'positive'
                  ? 'train-finding ts-primary'
                  : f.type === 'warning'
                    ? 'train-finding ts-warning'
                    : 'train-finding'
              }
            >
              • {f.message}
            </Text>
          ))}
        </View>
      )}

      {diagnosis.suggestions.length > 0 && (
        <View className="ts-card">
          <Text className="ts-section-label">Suggestions</Text>
          {diagnosis.suggestions.map((s, i) => (
            <Text key={i} className="train-finding">{i + 1}. {s}</Text>
          ))}
        </View>
      )}
    </View>
  );
}

/**
 * Very simple zone bar — actual as filled bar, target as a vertical tick.
 * No SVG/canvas needed; plain nested Views scale well to any mini-program
 * renderer and render identically on iOS/Android WeChat.
 */
function ZoneBar({
  name,
  actual,
  target,
}: {
  name: string;
  actual: number;
  target: number | null;
}) {
  const actualClamped = Math.max(0, Math.min(100, actual));
  const targetClamped = target != null ? Math.max(0, Math.min(100, target)) : null;
  return (
    <View className="train-zonebar">
      <View className="train-zonebar-head">
        <Text className="train-zonebar-name">{name}</Text>
        <Text className="train-zonebar-value ts-value">
          {actual.toFixed(0)}%{target != null ? ` / ${target.toFixed(0)}%` : ''}
        </Text>
      </View>
      <View className="train-zonebar-track">
        <View
          className="train-zonebar-fill"
          style={{ width: `${actualClamped}%` }}
        />
        {targetClamped != null && (
          <View
            className="train-zonebar-target"
            style={{ left: `${targetClamped}%` }}
          />
        )}
      </View>
    </View>
  );
}
