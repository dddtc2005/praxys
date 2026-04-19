import { useCallback, useEffect, useState } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro, { useReachBottom, usePullDownRefresh } from '@tarojs/taro';

import { apiGet, ApiError } from '@/lib/api-client';
import type { Activity, HistoryResponse } from '@/types/api';
import { formatDistance, formatTime } from '@/lib/format';
import './index.scss';

/**
 * Activities feed. Infinite-scroll style (useReachBottom fires when the
 * user scrolls to the bottom of the list) rather than pagination
 * buttons — mobile users expect this pattern.
 */
const PAGE_SIZE = 20;

export default function HistoryPage() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [offset, setOffset] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const fetchPage = useCallback(async (nextOffset: number, replace: boolean) => {
    const isInitial = replace;
    if (isInitial) setLoading(true);
    else setLoadingMore(true);
    setError(null);
    try {
      const resp = await apiGet<HistoryResponse>(
        `/api/history?limit=${PAGE_SIZE}&offset=${nextOffset}`,
      );
      setTotal(resp.total);
      setActivities((prev) => (replace ? resp.activities : [...prev, ...resp.activities]));
      setOffset(nextOffset + resp.activities.length);
    } catch (e) {
      setError((e as Partial<ApiError>)?.detail ?? String(e));
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    void fetchPage(0, true);
  }, [fetchPage]);

  useReachBottom(() => {
    if (loadingMore || loading) return;
    if (activities.length >= total) return;
    void fetchPage(offset, false);
  });

  usePullDownRefresh(async () => {
    await fetchPage(0, true);
    Taro.stopPullDownRefresh();
  });

  function toggleExpand(id: string) {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  if (loading && activities.length === 0) {
    return (
      <View className="history-root">
        <Text className="history-header">Activities</Text>
        {[0, 1, 2].map((i) => (
          <View key={i} className="ts-card">
            <View className="ts-skeleton" style={{ height: '120rpx' }} />
          </View>
        ))}
      </View>
    );
  }

  if (error && activities.length === 0) {
    return (
      <View className="history-root">
        <Text className="history-header ts-destructive">Failed to load</Text>
        <Text>{error}</Text>
        <Button className="ts-button" onClick={() => fetchPage(0, true)}>Retry</Button>
      </View>
    );
  }

  return (
    <View className="history-root">
      <View className="history-header-row">
        <Text className="history-header">Activities</Text>
        <Text className="history-total ts-muted">
          {total} total · showing {activities.length}
        </Text>
      </View>

      {activities.map((a) => (
        <ActivityRow
          key={a.activity_id}
          activity={a}
          expanded={!!expanded[a.activity_id]}
          onToggle={() => toggleExpand(a.activity_id)}
        />
      ))}

      {loadingMore && (
        <Text className="history-footer ts-muted">Loading more…</Text>
      )}
      {!loadingMore && activities.length >= total && total > 0 && (
        <Text className="history-footer ts-muted">End of history</Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Activity row with collapsible splits.
// ---------------------------------------------------------------------------

function ActivityRow({
  activity,
  expanded,
  onToggle,
}: {
  activity: Activity;
  expanded: boolean;
  onToggle: () => void;
}) {
  const hasSplits = activity.splits && activity.splits.length > 0;
  return (
    <View className="ts-card history-row" onClick={onToggle}>
      <View className="history-row-head">
        <Text className="history-row-date ts-muted">{activity.date}</Text>
        <Text className="history-row-type">{activity.activity_type}</Text>
      </View>
      <View className="history-row-metrics">
        {activity.distance_km != null && (
          <Metric label="km" value={formatDistance(activity.distance_km)} />
        )}
        {activity.duration_sec != null && (
          <Metric label="time" value={formatTime(activity.duration_sec)} />
        )}
        {activity.avg_power != null && (
          <Metric label="avg W" value={`${activity.avg_power.toFixed(0)}`} />
        )}
        {activity.avg_hr != null && (
          <Metric label="avg HR" value={`${activity.avg_hr.toFixed(0)}`} />
        )}
      </View>

      {hasSplits && expanded && (
        <View className="history-splits">
          <Text className="ts-section-label">Splits ({activity.splits.length})</Text>
          {activity.splits.slice(0, 20).map((s) => (
            <View key={s.split_num} className="history-split-row">
              <Text className="history-split-num ts-muted">#{s.split_num}</Text>
              {s.distance_km != null && (
                <Text className="history-split-cell ts-value">
                  {formatDistance(s.distance_km)}
                </Text>
              )}
              {s.duration_sec != null && (
                <Text className="history-split-cell ts-value">
                  {formatTime(s.duration_sec)}
                </Text>
              )}
              {s.avg_power != null && (
                <Text className="history-split-cell ts-value">
                  {s.avg_power.toFixed(0)} W
                </Text>
              )}
            </View>
          ))}
          {activity.splits.length > 20 && (
            <Text className="ts-muted history-split-more">
              + {activity.splits.length - 20} more
            </Text>
          )}
        </View>
      )}

      {hasSplits && !expanded && (
        <Text className="history-tap-hint ts-muted">
          Tap to view {activity.splits.length} splits
        </Text>
      )}
    </View>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View className="history-metric">
      <Text className="history-metric-label ts-muted">{label}</Text>
      <Text className="history-metric-value ts-value">{value}</Text>
    </View>
  );
}
