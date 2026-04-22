import { View, Text, Button } from '@tarojs/components';
import Taro, { usePullDownRefresh, useDidShow } from '@tarojs/taro';

import { useApi } from '@/hooks/useApi';
import type { TodayResponse } from '@/types/api';
import { formatDistance, formatTime } from '@/lib/format';
import { applyThemeChrome, themeClassName } from '@/lib/theme';
import LineChart from '@/components/LineChart';
import './index.scss';

/**
 * Today view — the training signal (Go / Easy / Modify / Rest), recovery
 * snapshot, and the next planned workout. Charts (form sparkline, etc.)
 * are deferred to a later pass because mini-program-friendly chart libs
 * (echarts-for-weixin, visactor) need their own integration work.
 */
export default function TodayPage() {
  const { data, loading, error, refetch } = useApi<TodayResponse>('/api/today');

  useDidShow(() => applyThemeChrome());

  // WeChat's standard "pull down to refresh" gesture → re-fetch.
  usePullDownRefresh(() => {
    refetch();
    Taro.stopPullDownRefresh();
  });

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });

  if (loading && !data) {
    return (
      <View className={`today-root ${themeClassName()}`}>
        <Text className="today-header">Today</Text>
        <Text className="today-date">{today}</Text>
        <View className="ts-card">
          <View className="ts-skeleton" style={{ height: '180rpx' }} />
        </View>
        <View className="ts-card">
          <View className="ts-skeleton" />
        </View>
      </View>
    );
  }

  if (error) {
    return (
      <View className={`today-root ${themeClassName()}`}>
        <Text className="today-header ts-destructive">Failed to load</Text>
        <Text className="today-date">{error}</Text>
        <Button className="ts-button" onClick={() => refetch()}>Retry</Button>
      </View>
    );
  }

  if (!data) {
    return (
      <View className={`today-root ${themeClassName()}`}>
        <Text className="today-header">Today</Text>
        <Text className="today-date">No data available yet.</Text>
      </View>
    );
  }

  const { signal, recovery_analysis, last_activity, upcoming, warnings, tsb_sparkline } = data;
  const hasSparkline = tsb_sparkline && tsb_sparkline.values.length >= 2;

  return (
    <View className={`today-root ${themeClassName()}`}>
      <Text className="today-header">Today</Text>
      <Text className="today-date">{today}</Text>

      <SignalCard signal={signal.recommendation} reason={signal.reason} />

      {hasSparkline && (
        <View className="ts-card">
          <Text className="ts-section-label">Form (TSB)</Text>
          <FormHeadline
            tsb={
              signal?.recovery?.tsb ??
              tsb_sparkline.values[tsb_sparkline.values.length - 1] ??
              null
            }
          />
          <LineChart
            canvasId="today-sparkline"
            height={200}
            showLegend={false}
            showZeroLine
            dates={tsb_sparkline.dates}
            series={[
              {
                label: 'TSB',
                color: '#3b82f6',
                values: tsb_sparkline.values,
                fill: true,
              },
            ]}
          />
        </View>
      )}

      <View className="ts-card">
        <Text className="ts-section-label">Recovery</Text>
        <RecoveryRow label="Status" value={recovery_analysis?.status ?? '—'} />
        <RecoveryRow
          label="HRV"
          value={
            recovery_analysis?.hrv?.today_ms != null
              ? `${recovery_analysis.hrv.today_ms.toFixed(0)} ms`
              : '—'
          }
        />
        <RecoveryRow
          label="Resting HR"
          value={
            recovery_analysis?.resting_hr != null
              ? `${recovery_analysis.resting_hr.toFixed(0)} bpm`
              : '—'
          }
        />
        <RecoveryRow
          label="Sleep"
          value={
            recovery_analysis?.sleep_score != null
              ? `${recovery_analysis.sleep_score.toFixed(0)}/100`
              : '—'
          }
        />
      </View>

      {upcoming && upcoming.length > 0 && (
        <View className="ts-card">
          <Text className="ts-section-label">Upcoming workouts</Text>
          {upcoming.slice(0, 3).map((w) => (
            <View key={w.date} className="today-upcoming-row">
              <Text className="today-upcoming-date">{w.date}</Text>
              <Text className="today-upcoming-name">{w.workout_type}</Text>
              {w.duration_min != null && (
                <Text className="today-upcoming-meta">
                  {w.duration_min} min
                </Text>
              )}
            </View>
          ))}
        </View>
      )}

      {last_activity && (
        <View className="ts-card">
          <Text className="ts-section-label">Last activity</Text>
          <Text className="today-last-date">{last_activity.date}</Text>
          <View className="today-last-metrics">
            {last_activity.distance_km != null && (
              <Metric label="Distance" value={formatDistance(last_activity.distance_km)} />
            )}
            {last_activity.duration_sec != null && (
              <Metric label="Duration" value={formatTime(last_activity.duration_sec)} />
            )}
            {last_activity.avg_power != null && (
              <Metric label="Avg power" value={`${last_activity.avg_power.toFixed(0)} W`} />
            )}
          </View>
        </View>
      )}

      {warnings && warnings.length > 0 && (
        <View className="ts-card today-warnings">
          <Text className="ts-section-label">Warnings</Text>
          {warnings.map((w, i) => (
            <Text key={i} className="today-warning-item ts-warning">• {w}</Text>
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Signal card
// ---------------------------------------------------------------------------

const SIGNAL_META: Record<string, { label: string; accent: string; title: string }> = {
  follow_plan: { label: 'GO', accent: 'ts-primary', title: 'Follow your plan' },
  easy: { label: 'EASY', accent: 'ts-primary', title: 'Keep it easy today' },
  modify: { label: 'MODIFY', accent: 'ts-warning', title: 'Adjust your plan' },
  reduce_intensity: { label: 'EASE OFF', accent: 'ts-warning', title: 'Reduce intensity' },
  rest: { label: 'REST', accent: 'ts-destructive', title: 'Rest today' },
};

function SignalCard({
  signal,
  reason,
}: {
  signal: TodayResponse['signal']['recommendation'];
  reason: string;
}) {
  const meta = SIGNAL_META[signal] ?? SIGNAL_META.follow_plan;
  return (
    <View className="ts-card today-signal">
      <Text className={`today-signal-label ${meta.accent}`}>{meta.label}</Text>
      <Text className="today-signal-title">{meta.title}</Text>
      <Text className="today-signal-reason">{reason}</Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Form headline — current TSB value + zone badge
// ---------------------------------------------------------------------------

/**
 * Map a TSB value to a textual zone name + an accent class. Thresholds are
 * the widely-used Banister-style bands; Praxys's science page shows
 * exact zone boundaries for whichever load theory is active, so this
 * headline is a quick-glance summary, not the source of truth.
 *
 * The web app's FormSparkline uses the same buckets.
 */
function tsbZone(tsb: number): { label: string; accent: string } {
  if (tsb > 25) return { label: 'Peaked', accent: 'ts-warning' };
  if (tsb >= 5) return { label: 'Fresh', accent: 'ts-primary' };
  if (tsb >= -10) return { label: 'Neutral', accent: '' };
  if (tsb >= -30) return { label: 'Fatigued', accent: 'ts-warning' };
  return { label: 'Over-fatigued', accent: 'ts-destructive' };
}

function FormHeadline({ tsb }: { tsb: number | null | undefined }) {
  if (tsb == null) {
    return <Text className="today-tsb-headline ts-muted">No TSB data yet</Text>;
  }
  const zone = tsbZone(tsb);
  return (
    <View className="today-tsb-headline-row">
      <Text className="today-tsb-value ts-value">
        {tsb >= 0 ? '+' : ''}
        {tsb.toFixed(1)}
      </Text>
      <Text className={`today-tsb-zone ${zone.accent}`}>{zone.label}</Text>
    </View>
  );
}

function RecoveryRow({ label, value }: { label: string; value: string }) {
  return (
    <View className="today-recovery-row">
      <Text className="today-recovery-label ts-muted">{label}</Text>
      <Text className="today-recovery-value ts-value">{value}</Text>
    </View>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View className="today-metric">
      <Text className="today-metric-label ts-muted">{label}</Text>
      <Text className="today-metric-value ts-value">{value}</Text>
    </View>
  );
}
