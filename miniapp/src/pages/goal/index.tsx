import { View, Text, Button } from '@tarojs/components';
import Taro, { usePullDownRefresh, useDidShow } from '@tarojs/taro';

import { useApi } from '@/hooks/useApi';
import type { GoalResponse } from '@/types/api';
import { formatTime } from '@/lib/format';
import { applyThemeChrome, themeClassName } from '@/lib/theme';
import LineChart from '@/components/LineChart';
import './index.scss';

/**
 * Goal view — race countdown + predicted time + CP gap. The full web
 * Goal page has a chart of CP over time; that's deferred until we pick
 * a Taro-compatible chart library.
 */
export default function GoalPage() {
  const { data, loading, error, refetch } = useApi<GoalResponse>('/api/goal');
  useDidShow(() => applyThemeChrome());
  usePullDownRefresh(() => {
    refetch();
    Taro.stopPullDownRefresh();
  });

  if (loading && !data) {
    return (
      <View className={`goal-root ${themeClassName()}`}>
        <Text className="goal-header">Goal</Text>
        <View className="ts-card"><View className="ts-skeleton" /></View>
      </View>
    );
  }

  if (error) {
    return (
      <View className={`goal-root ${themeClassName()}`}>
        <Text className="goal-header ts-destructive">Failed to load</Text>
        <Text>{error}</Text>
        <Button className="ts-button" onClick={() => refetch()}>Retry</Button>
      </View>
    );
  }

  if (!data) return null;
  const rc = data.race_countdown;
  const hasCpTrend = data.cp_trend && data.cp_trend.values.length >= 2;

  if (rc.mode === 'none') {
    return (
      <View className={`goal-root ${themeClassName()}`}>
        <Text className="goal-header">Goal</Text>
        <View className="ts-card">
          <Text className="ts-muted">
            No goal configured. Set a race date or a continuous-improvement
            target on the web Settings page.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View className={`goal-root ${themeClassName()}`}>
      <Text className="goal-header">Goal</Text>

      {rc.days_left != null && (
        <View className="ts-card goal-countdown">
          <Text className="goal-countdown-value ts-value">{rc.days_left}</Text>
          <Text className="goal-countdown-label ts-muted">days to race</Text>
        </View>
      )}

      {rc.predicted_time_sec != null && (
        <View className="ts-card">
          <Text className="ts-section-label">Predicted finish</Text>
          <Text className="goal-big ts-value">{formatTime(rc.predicted_time_sec)}</Text>
          {rc.target_time_sec != null && (
            <Text className="goal-target-line">
              Target: {formatTime(rc.target_time_sec)}
            </Text>
          )}
        </View>
      )}

      {rc.cp_gap_watts != null && (
        <View className="ts-card">
          <Text className="ts-section-label">CP gap</Text>
          <Text className="goal-big ts-value">
            {rc.cp_gap_watts >= 0 ? '+' : ''}
            {rc.cp_gap_watts.toFixed(0)} W
          </Text>
          {rc.current_cp != null && rc.target_cp != null && (
            <Text className="goal-gap-range">
              {rc.current_cp.toFixed(0)} W → {rc.target_cp.toFixed(0)} W
            </Text>
          )}
        </View>
      )}

      {rc.reality_check && (
        <View className="ts-card">
          <Text className="ts-section-label">Reality check</Text>
          <Text className="goal-assessment">
            {rc.reality_check.assessment}
          </Text>
          {rc.reality_check.trend_note && (
            <Text className="goal-trend-note">{rc.reality_check.trend_note}</Text>
          )}
        </View>
      )}

      {hasCpTrend && (
        <View className="ts-card">
          <Text className="ts-section-label">CP trend</Text>
          <LineChart
            canvasId="goal-cp-trend"
            height={240}
            showLegend={false}
            dates={data.cp_trend.dates}
            series={[
              { label: 'CP', color: '#44d08e', values: data.cp_trend.values, fill: true },
            ]}
          />
        </View>
      )}
    </View>
  );
}
