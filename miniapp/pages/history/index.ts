import { setTabBarSelected } from '../../utils/tabbar';
import type { IAppOption } from '../../app';
import { apiGet } from '../../utils/api-client';
import type { ApiError } from '../../utils/api-client';
import type { Activity, HistoryResponse } from '../../types/api';
import { formatDistance, formatTime } from '../../utils/format';
import { applyThemeChrome, themeClassName } from '../../utils/theme';
import { t, tFmt } from '../../utils/i18n';

function buildHistoryTr() {
  return {
    navTitle: t('Activities'),
    activities: t('Activities'),
    failedToLoad: t('Failed to load'),
    retry: t('Retry'),
    loadingMore: t('Loading more…'),
    endOfActivities: t('End of activities'),
    splits: t('Splits'),
    more: t('more'),
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
  themeClass: getApp<IAppOption>().globalData.themeClass,
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

function formatActivityType(raw: string): string {
  // Split on underscores, capitalise each word, then run through t() for locale.
  // The formatted string is intentionally used as the t() key — known types
  // (Running, Cycling) get translated; unknown types fall back to the formatted
  // English string via t()'s key-is-fallback behaviour.
  const formatted = raw
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
  return t(formatted);
}

function buildActivityRow(activity: Activity): ActivityRow {
  const metrics: MetricRow[] = [];
  if (activity.distance_km != null) {
    metrics.push({ label: t('km'), value: formatDistance(activity.distance_km) });
  }
  if (activity.duration_sec != null) {
    metrics.push({ label: t('time'), value: formatTime(activity.duration_sec) });
  }
  if (activity.avg_power != null) {
    metrics.push({ label: t('avg W'), value: `${activity.avg_power.toFixed(0)}` });
  }
  if (activity.avg_hr != null) {
    metrics.push({ label: t('avg HR'), value: `${activity.avg_hr.toFixed(0)}` });
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
    type: formatActivityType(activity.activity_type),
    metrics,
    hasSplits,
    splitCount: splits.length,
    splitsDisplay,
    hasMoreSplits: splits.length > 20,
    moreSplitsCount: Math.max(0, splits.length - 20),
    expanded: false,
    tapHint: hasSplits ? tFmt('Tap to view {0} splits', splits.length) : '',
  };
}

Page({
  data: { ...initialData, tr: buildHistoryTr() },

  onLoad() {
    this.setData({ themeClass: themeClassName(), tr: buildHistoryTr() });
    void this.fetchPage(0, true);
  },

  onShow() {
    // Guarded theme update: other tabs can't be reached by getCurrentPages()
    // from Settings, so if the user changed theme while on another tab,
    // this is the first chance to apply it. Equality check prevents
    // re-renders on normal tab switches where nothing changed.
    const tc = themeClassName();
    if (tc !== this.data.themeClass) {
      this.setData({ themeClass: tc });
    }
    // Locale guard: rebuilds tr when language changed while this tab
    // was not active (same pattern as theme — globalData stores the
    // active locale so we detect drift without a storage read).
    const curLocale = getApp<IAppOption>().globalData.locale;
    const pgMut = this as unknown as Record<string, unknown>;
    if (curLocale !== pgMut._locale) {
      pgMut._locale = curLocale;
      this.setData({ tr: buildHistoryTr() });
      void this.fetchPage(0, true);
    }
    applyThemeChrome();
    setTabBarSelected(this, 2);
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
        totalLine: tFmt('{0} total · showing {1}', resp.total, merged.length),
        offset,
      });
    } catch (e) {
      const err = e as Partial<ApiError>;
      if (err?.code === 'UNAUTHENTICATED') {
        this.setData({ loading: false, loadingMore: false });
        return;
      }
      const detail = err?.detail ?? String(e);
      this.setData({
        loading: false,
        loadingMore: false,
        errorMessage: detail,
      });
    }
  },
});
