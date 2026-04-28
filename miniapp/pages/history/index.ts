import { apiGet } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import type { Activity, HistoryResponse } from '../../types/api';
import { formatDistance, formatTime } from '../../utils/format';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { t } from '../../utils/i18n';

function buildHistoryTr() {
  return {
    activities: t('Activities'),
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    loadingMore: t('Loading more…'),
    endOfActivities: t('End of activities'),
  };
}

const PAGE_SIZE = 20;

interface MetricRow {
  label: string;
  value: string;
}

interface SplitRow {
  num: string;
  cells: string[];
}

interface ActivityRow {
  id: string;
  date: string;
  type: string;
  metrics: MetricRow[];
  hasSplits: boolean;
  splitCount: number;
  splitsDisplay: SplitRow[];
  hasMoreSplits: boolean;
  moreSplitsCount: number;
  expanded: boolean;
  tapHint: string;
}

interface HistoryState {
  themeClass: string;
  loading: boolean;
  loadingMore: boolean;
  errorMessage: string;
  activities: ActivityRow[];
  total: number;
  shownCount: number;
  hasActivities: boolean;
  hasReachedEnd: boolean;
  totalLine: string;
  offset: number;
  refreshing: boolean;
}

const initialData: HistoryState = {
  themeClass: 'theme-light',
  loading: true,
  loadingMore: false,
  errorMessage: '',
  activities: [],
  total: 0,
  shownCount: 0,
  hasActivities: false,
  hasReachedEnd: false,
  totalLine: '',
  offset: 0,
  refreshing: false,
};

function buildActivityRow(activity: Activity): ActivityRow {
  const metrics: MetricRow[] = [];
  if (activity.distance_km != null) {
    metrics.push({ label: 'km', value: formatDistance(activity.distance_km) });
  }
  if (activity.duration_sec != null) {
    metrics.push({ label: 'time', value: formatTime(activity.duration_sec) });
  }
  if (activity.avg_power != null) {
    metrics.push({ label: 'avg W', value: `${activity.avg_power.toFixed(0)}` });
  }
  if (activity.avg_hr != null) {
    metrics.push({ label: 'avg HR', value: `${activity.avg_hr.toFixed(0)}` });
  }

  const splits = activity.splits ?? [];
  const hasSplits = splits.length > 0;
  const splitsDisplay: SplitRow[] = splits.slice(0, 20).map((s) => {
    const cells: string[] = [];
    if (s.distance_km != null) cells.push(formatDistance(s.distance_km));
    if (s.duration_sec != null) cells.push(formatTime(s.duration_sec));
    if (s.avg_power != null) cells.push(`${s.avg_power.toFixed(0)} W`);
    return { num: `#${s.split_num}`, cells };
  });

  return {
    id: activity.activity_id,
    date: activity.date,
    type: activity.activity_type,
    metrics,
    hasSplits,
    splitCount: splits.length,
    splitsDisplay,
    hasMoreSplits: splits.length > 20,
    moreSplitsCount: Math.max(0, splits.length - 20),
    expanded: false,
    tapHint: hasSplits ? `Tap to view ${splits.length} splits` : '',
  };
}

Page({
  data: { ...initialData, tr: buildHistoryTr() },

  onLoad() {
    this.setData({ themeClass: themeClassName() });
    void this.fetchPage(0, true);
  },

  onShow() {
    applyThemeChrome();
    const tabBar = (this as { getTabBar?: () => { setData: (d: unknown) => void } | null })
      .getTabBar?.();
    tabBar?.setData({ selected: 2 });
  },

  onScrollToBottom() {
    // Skyline scroll-view fires bindscrolltolower instead of the page's
    // onReachBottom. Same guard logic to avoid concurrent fetches.
    if (this.data.loadingMore || this.data.loading) return;
    if (this.data.activities.length >= this.data.total) return;
    void this.fetchPage(this.data.offset, false);
  },

  onScrollRefresh() {
    this.setData({ refreshing: true });
    void this.fetchPage(0, true).finally(() => this.setData({ refreshing: false }));
  },

  onRetry() {
    void this.fetchPage(0, true);
  },

  toggleExpand(e: WechatMiniprogram.TouchEvent) {
    const id = e.currentTarget.dataset.id as string | undefined;
    if (!id) return;
    const next = (this.data.activities as ActivityRow[]).map((a) =>
      a.id === id ? { ...a, expanded: !a.expanded } : a,
    );
    this.setData({ activities: next });
  },

  async fetchPage(nextOffset: number, replace: boolean) {
    if (replace) {
      this.setData({ loading: true, errorMessage: '' });
    } else {
      this.setData({ loadingMore: true, errorMessage: '' });
    }
    try {
      const resp = await apiGet<HistoryResponse>(
        `/api/history?limit=${PAGE_SIZE}&offset=${nextOffset}`,
      );
      const newRows = resp.activities.map(buildActivityRow);
      const merged: ActivityRow[] = replace
        ? newRows
        : [...(this.data.activities as ActivityRow[]), ...newRows];
      const offset = nextOffset + resp.activities.length;
      this.setData({
        loading: false,
        loadingMore: false,
        activities: merged,
        total: resp.total,
        shownCount: merged.length,
        hasActivities: merged.length > 0,
        hasReachedEnd: merged.length >= resp.total && resp.total > 0,
        totalLine: `${resp.total} total · showing ${merged.length}`,
        offset,
      });
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') return;
      const detail = err?.detail ?? String(e);
      this.setData({
        loading: false,
        loadingMore: false,
        errorMessage: detail,
      });
    }
  },
});
