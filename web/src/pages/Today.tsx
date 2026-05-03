import { useState } from 'react';
import { useApi, API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { AiInsight, TodayResponse, TrainingSignal } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { msg } from '@lingui/core/macro';
import { Trans, useLingui } from '@lingui/react/macro';
import type { MessageDescriptor } from '@lingui/core';
import { useLocale } from '@/contexts/LocaleContext';
import AiInsightsCard from '@/components/AiInsightsCard';

// Skeleton mirrors the today-spread layout shape so the page doesn't flash
// from the old space-y-6 grid into the new asymmetric layout when data
// resolves. Each child here gets the same grid-placement class as its
// real-content counterpart.
function TodaySkeleton() {
  return (
    <div className="today-spread">
      <h1 className="sr-only"><Trans>Today</Trans></h1>
      <div className="today-eyebrow"><Skeleton className="h-4 w-56" /></div>
      <div className="today-verdict">
        <Skeleton className="rounded-full h-44 w-44 sm:h-56 sm:w-56" />
        <Skeleton className="h-6 w-28" />
      </div>
      <div className="coach-receipt">
        <div className="coach-banner">
          <Skeleton className="h-3 w-24 bg-card/30" />
          <Skeleton className="h-3 w-12 bg-card/30" />
        </div>
        <div className="coach-body">
          <Skeleton className="h-4 w-3/4 mb-3" />
          <Skeleton className="h-3 w-full mb-2" />
          <Skeleton className="h-3 w-full mb-2" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      </div>
      <div className="today-supporting">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="today-cell">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-6 w-12" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>
      <div className="today-plan">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-4 w-48" />
      </div>
    </div>
  );
}

const VERDICT_LABEL: Record<TrainingSignal['recommendation'], MessageDescriptor> = {
  follow_plan: msg`GO`,
  easy: msg`EASY`,
  modify: msg`MODIFY`,
  reduce_intensity: msg`CAUTION`,
  rest: msg`REST`,
};

// Subtitle casing intentionally matches SignalHero.tsx's existing strings
// (title case: "Go Easy", "Follow Plan", etc.) so the same translation
// catalogue entries cover both surfaces — no duplicate zh keys.
const VERDICT_SUBTITLE: Record<TrainingSignal['recommendation'], MessageDescriptor> = {
  follow_plan: msg`Follow Plan`,
  easy: msg`Go Easy`,
  modify: msg`Adjust Workout`,
  reduce_intensity: msg`Reduce Intensity`,
  rest: msg`Recovery Day`,
};

type SignalTone = 'green' | 'amber' | 'red';

const VERDICT_TONE: Record<TrainingSignal['recommendation'], SignalTone> = {
  follow_plan: 'green',
  easy: 'amber',
  modify: 'amber',
  reduce_intensity: 'amber',
  rest: 'red',
};

// Glow color is theme-aware via CSS custom properties — see :root / .dark in
// index.css. Light theme uses the darker on-paper hue; dark theme uses the
// vivid neon variant. Matches the rest of the accent system.
const TONE_CLASSES: Record<SignalTone, { text: string; bg: string; ring: string; shadow: string }> = {
  green: {
    text: 'text-primary',
    bg: 'bg-primary',
    ring: 'ring-accent-green/30',
    shadow: 'shadow-[0_0_40px_var(--shadow-glow-primary)]',
  },
  amber: {
    text: 'text-accent-amber',
    bg: 'bg-accent-amber',
    ring: 'ring-accent-amber/30',
    shadow: 'shadow-[0_0_40px_var(--shadow-glow-amber)]',
  },
  red: {
    text: 'text-destructive',
    bg: 'bg-destructive',
    ring: 'ring-accent-red/30',
    shadow: 'shadow-[0_0_40px_var(--shadow-glow-red)]',
  },
};

const TREND_ARROW = { stable: '→', improving: '↑', declining: '↓' } as const;

const HRV_TREND_LABEL: Record<'stable' | 'improving' | 'declining', MessageDescriptor> = {
  stable: msg`stable`,
  improving: msg`improving`,
  declining: msg`declining`,
};

// rhr_trend from the API can be 'stable' | 'elevated' | 'low' | null. The
// 'normal' label is the historical fallback used when the trend is absent —
// it's not an API-emitted value, but the cell text already used it before
// i18n. Worth revisiting whether the cell should hide the trend chip
// entirely when null instead of saying "normal".
const RHR_TREND_LABEL: Record<'stable' | 'elevated' | 'low' | 'normal', MessageDescriptor> = {
  stable: msg`stable`,
  elevated: msg`elevated`,
  low: msg`low`,
  normal: msg`normal`,
};

// Banister PMC interpretation of training stress balance (TSB):
//   ≥ +10  strongly positive — peaked freshness, primed to perform
//   0..10  positive — freshness, training adapted
//   -10..0 mild fatigue — adaptation in progress
//   < -10  fatigued — accumulated fatigue, recovery prioritized
// Source: Banister, E.W. (1991). Modeling elite athletic performance.
// In: Physiological Testing of Elite Athletes (MacDougall, Wenger, Green eds.).
const TSB_STRONGLY_POSITIVE = 10;
const TSB_MILD_FATIGUE = -10;

// Format an ISO `YYYY-MM-DD` as a localized long-form date string. Parses
// the date as a local calendar date (not UTC midnight) so a server-emitted
// "2026-05-02" doesn't shift backward for users in negative-offset timezones
// — `new Date("2026-05-02")` would be UTC and render as May 1 in the
// Americas. Falls back to the raw ISO string if the parse fails.
function formatIsoDateLong(isoDate: string, locale: string): string {
  const [y, m, day] = isoDate.split('-').map(Number);
  if (!y || !m || !day) return isoDate;
  return new Date(y, m - 1, day).toLocaleDateString(
    locale === 'zh' ? 'zh-CN' : 'en-US',
    { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' },
  );
}

// Short ("Apr 24" / "4月24日") variant for the staleness banner so the
// reading-date chip sits inline cleanly. Same local-calendar parse as
// formatIsoDateLong — keep the two in sync.
function formatIsoDateShort(isoDate: string, locale: string): string {
  const [y, m, day] = isoDate.split('-').map(Number);
  if (!y || !m || !day) return isoDate;
  return new Date(y, m - 1, day).toLocaleDateString(
    locale === 'zh' ? 'zh-CN' : 'en-US',
    { month: 'short', day: 'numeric' },
  );
}

// Format the data_as_of timestamp for the staleness banner — local-TZ
// weekday + clock time ("Sat 9:00 PM" / "周六 21:00"). The server emits
// the timestamp with a trailing `Z`, so `new Date()` interprets it as
// UTC and renders in the user's local timezone, which is what we want
// the user to read.
function formatDataAsOf(iso: string, locale: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit',
  });
}

// Decide whether the page-level "yesterday's snapshot" banner should
// fire. The data row's calendar date in the user's local timezone is
// compared to the local today — if older, the banner goes up. Returns
// false on null data_as_of (fresh user, nothing to anchor on) and on
// invalid timestamps (don't lie when the server emits something weird).
function isDataStale(dataAsOf: string | null | undefined): boolean {
  if (!dataAsOf) return false;
  const d = new Date(dataAsOf);
  if (Number.isNaN(d.getTime())) return false;
  const dataLocalDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const now = new Date();
  const todayLocalDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  return dataLocalDate < todayLocalDate;
}

function formatPlan(plan: TrainingSignal['plan']): string | null {
  if (!plan?.workout_type) return null;
  const parts: string[] = [plan.workout_type];
  if (plan.distance_km != null) parts.push(`${plan.distance_km.toFixed(1)} km`);
  if (plan.duration_min != null) parts.push(`${plan.duration_min} min`);
  if (plan.power_min != null && plan.power_max != null) {
    parts.push(`${plan.power_min}–${plan.power_max} W`);
  }
  return parts.join(' · ');
}

export default function Today() {
  const { data, loading, error, refetch } = useApi<TodayResponse>('/api/today');
  // Same query key as AiInsightsCard, so React Query dedupes the fetch.
  const { data: briefData } = useApi<{ insight: AiInsight | null }>('/api/insights/daily_brief');
  const { locale } = useLocale();
  const { i18n } = useLingui();

  // Page-level data-staleness state. ``dismissed`` is the "Show anyway"
  // escape hatch — component-scoped (not localStorage) so each fresh
  // page load re-prompts. ``syncing`` flips while a manual sync is
  // running so the button can render a loading state without blocking
  // the rest of the page.
  const [dismissed, setDismissed] = useState(false);
  const [syncing, setSyncing] = useState(false);

  if (loading) return <TodaySkeleton />;

  if (error) {
    return (
      <Alert variant="destructive" className="my-12">
        <AlertTitle><Trans>Failed to load</Trans></AlertTitle>
        <AlertDescription className="flex items-center justify-between">
          <span>{error}</span>
          <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (!data) return null;

  const { signal, recovery_analysis: ra } = data;

  // Eyebrow date is sourced from the server's `as_of_date` rather than
  // `new Date()` — the page asserts what date the *data* was computed
  // for, not what the device's clock currently reads. A traveler whose
  // device crossed midnight before sync caught up would otherwise see
  // "May 2" on a payload the server still treats as May 1.
  const dateStr = formatIsoDateLong(data.as_of_date, locale);

  // Recovery staleness: the latest HRV/sleep row may be older than the
  // server's `as_of_date` when sync hasn't run yet today. The server
  // already applies a 1-day grace (sleep is recorded under the prior
  // night), so `is_stale` only fires when the gap is ≥ 2 days. We
  // intentionally don't try to detect "client local date != server
  // date" as a separate timezone-jump signal — the server runs in a
  // single fixed tz (UTC on Azure), so a 1-day offset is the steady
  // state for half the world. Letting the eyebrow render `as_of_date`
  // honestly is enough; speculating about timezones would lie to most
  // users every day during the hours their local rollover lags UTC.
  const recoveryStale = ra?.is_stale === true && !!ra.latest_date;
  const recoveryLatestLabel = recoveryStale && ra?.latest_date
    ? formatIsoDateShort(ra.latest_date, locale)
    : null;

  const verdictText = i18n._(VERDICT_LABEL[signal.recommendation] ?? VERDICT_LABEL.follow_plan);
  const verdictSubtitle = i18n._(VERDICT_SUBTITLE[signal.recommendation] ?? VERDICT_SUBTITLE.follow_plan);
  const tone = TONE_CLASSES[VERDICT_TONE[signal.recommendation] ?? 'amber'];
  // AiInsightsCard self-fetches /api/insights/daily_brief; React Query
  // dedupes against the briefData fetch above. Today only needs the
  // boolean to know whether to suppress the rule-based reason fallback.
  const hasCoachBrief = briefData?.insight != null;

  const hrv = ra?.hrv ?? null;
  const trendArrow = hrv ? TREND_ARROW[hrv.trend] : '—';
  const trendLabel = hrv ? i18n._(HRV_TREND_LABEL[hrv.trend]) : '—';
  const trendCv = hrv != null ? `${hrv.rolling_cv.toFixed(1)}%` : '—';
  // Only show the RHR trend chip when the API actually emits one. Falling
  // back to the literal "normal" was the prior behavior, but it asserts
  // information that isn't there — better to render just `bpm` alone.
  const rhrTrendLabel = ra?.rhr_trend ? i18n._(RHR_TREND_LABEL[ra.rhr_trend]) : null;
  const baselineLabel = hrv ? i18n._(msg`vs ${hrv.baseline_mean_ln.toFixed(2)} baseline`) : i18n._(msg`no data`);
  const sleepScore = ra?.sleep_score;
  const readinessScore = ra?.readiness_score;
  const restingHr = ra?.resting_hr;
  const rhrDisplay = restingHr != null ? Math.round(restingHr) : '—';
  const tsb = signal.recovery.tsb;
  const tsbDisplay = `${tsb >= 0 ? '+' : ''}${tsb.toFixed(1)}`;
  const tsbDescriptorMsg =
    tsb >= TSB_STRONGLY_POSITIVE ? msg`strongly positive`
    : tsb > 0 ? msg`positive`
    : tsb > TSB_MILD_FATIGUE ? msg`mild fatigue`
    : msg`fatigued`;
  const tsbDescriptor = i18n._(tsbDescriptorMsg);
  const planText = formatPlan(signal.plan) ?? i18n._(msg`Rest day. No workout scheduled.`);

  // Theory attribution for the Coach receipt footer. Derived from the user's
  // active recovery + load theories; falls back to nothing if the API didn't
  // resolve them. Replaces the prior hardcoded "Plews HRV-guided · Banister
  // PMC" string, which would have shown wrong sources after a theory switch.
  const recoveryNoteName = data.science_notes?.recovery?.name;
  const loadNoteName = data.science_notes?.load?.name;
  const attribution = [recoveryNoteName, loadNoteName].filter(Boolean).join(' · ');

  // Page-level data-staleness — the user is looking at yesterday's
  // snapshot when the freshest data row's calendar date in their local
  // TZ is older than today. Anchors on the actual data timestamp, not
  // the sync-attempt time, so a successful sync that pulled no rows
  // correctly leaves the banner up. Suppresses the older recovery-only
  // banner when active, since this signal is strictly more general
  // (it fires for any stale data, not just recovery ≥2 days behind).
  const dataStale = isDataStale(data.data_as_of);
  const dataAsOfLabel = data.data_as_of ? formatDataAsOf(data.data_as_of, locale) : null;
  const showStaleBanner = dataStale && !!dataAsOfLabel && !dismissed;
  const showStaleChip = dataStale && !!dataAsOfLabel && dismissed;
  const showRecoveryBanner = !dataStale && recoveryStale && !!recoveryLatestLabel;

  // Manual sync — kicks the existing /api/sync route (background
  // tasks) and polls /api/sync/status until no source is still
  // ``syncing``. A bare ``setTimeout(6s)`` would re-enable the button
  // before Garmin's first-time fetch (30+ seconds for the initial
  // backfill) finishes; the user would see the button bounce back to
  // ``Sync now``, click again, and double-trigger. The 60s wall is the
  // hard upper bound — beyond that we refetch anyway and let the
  // banner re-arm if data_as_of didn't move (the honest "your sync is
  // taking longer than expected, here's where the data still sits"
  // signal). 2s polling cadence is the same one Settings.tsx uses
  // post-sync; matches the L3 cache's date-salt invalidation latency.
  const handleSyncNow = async () => {
    setSyncing(true);
    try {
      await fetch(`${API_BASE}/api/sync`, {
        method: 'POST',
        headers: getAuthHeaders() as Record<string, string>,
      });
      const deadline = Date.now() + 60_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 2_000));
        try {
          const res = await fetch(
            `${API_BASE}/api/sync/status`,
            { headers: getAuthHeaders() as Record<string, string> },
          );
          if (!res.ok) break;
          const status = (await res.json()) as Record<string, { status?: string }>;
          const stillSyncing = Object.values(status).some(
            (s) => s?.status === 'syncing',
          );
          if (!stillSyncing) break;
        } catch {
          // Transient network blip — keep polling. The deadline guards
          // against an indefinitely-broken status endpoint.
        }
      }
      await refetch();
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className={`today-spread ${showStaleBanner ? 'sync-stale' : ''}`.trim()}>
      <h1 className="today-eyebrow font-data"><Trans>Today</Trans> · {dateStr}</h1>
      {showStaleBanner && (
        <div role="status" aria-live="polite" className="today-data-stale-banner">
          <div className="stale-text">
            <span className="stale-headline">
              <Trans>Showing yesterday's snapshot. Last reading {dataAsOfLabel}.</Trans>
            </span>
            <span className="stale-detail font-data">
              <Trans>No new HRV, sleep, or activity since.</Trans>
            </span>
          </div>
          <div className="stale-actions">
            <Button
              size="sm"
              onClick={handleSyncNow}
              disabled={syncing}
            >
              {syncing ? <Trans>Syncing…</Trans> : <Trans>Sync now</Trans>}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setDismissed(true)}
            >
              <Trans>Show anyway</Trans>
            </Button>
          </div>
        </div>
      )}
      {showStaleChip && (
        <div className="today-data-stale-chip" role="status">
          <span className="stale-chip-dot" aria-hidden="true" />
          <span><Trans>From {dataAsOfLabel}</Trans></span>
          <button
            type="button"
            className="stale-chip-link"
            onClick={handleSyncNow}
            disabled={syncing}
          >
            {syncing ? <Trans>Syncing…</Trans> : <Trans>Sync now</Trans>}
          </button>
        </div>
      )}
      {showRecoveryBanner && (
        <div
          role="status"
          aria-live="polite"
          className="today-staleness-banner rounded-lg border border-dashed border-accent-amber/40 bg-accent-amber/5 px-3 py-2 text-xs text-accent-amber"
        >
          <Trans>
            Recovery data hasn't synced yet. Showing the latest reading from {recoveryLatestLabel}.
          </Trans>
        </div>
      )}
      <div className="today-verdict">
        <div
          className={`relative flex h-44 w-44 sm:h-56 sm:w-56 items-center justify-center rounded-full ring-4 ${tone.ring} ${tone.shadow}`}
          aria-hidden="true"
        >
          <div className={`absolute inset-0 rounded-full ${tone.bg} opacity-10 motion-safe:animate-pulse`} />
          <span className={`relative text-5xl sm:text-6xl font-bold font-data tracking-wider ${tone.text}`}>
            {verdictText}
          </span>
        </div>
        <p className={`text-xl font-semibold ${tone.text}`}>{verdictSubtitle}</p>
        {!hasCoachBrief && <p className="text-sm text-muted-foreground text-center max-w-sm">{signal.reason}</p>}
      </div>
      <AiInsightsCard insightType="daily_brief" attribution={attribution} />
      <div className={`today-supporting ${readinessScore != null ? 'today-supporting--6' : ''}`.trim()}>
        <div className="today-cell"><span className="today-cell-label">HRV (ln RMSSD)</span><span className="today-cell-value font-data">{hrv ? hrv.today_ln.toFixed(2) : '—'}</span><span className="today-cell-sub font-data">{hrv?.today_ms != null ? `${hrv.today_ms} ms · ` : ''}{baselineLabel}</span></div>
        <div className="today-cell"><span className="today-cell-label"><Trans>7d Trend</Trans></span><span className="today-cell-value font-data">{trendArrow}</span><span className="today-cell-sub font-data">{hrv ? `${trendLabel} · CV ${trendCv}` : i18n._(msg`no data`)}</span></div>
        <div className="today-cell"><span className="today-cell-label"><Trans>RHR</Trans></span><span className="today-cell-value font-data">{rhrDisplay}</span><span className="today-cell-sub font-data">{restingHr != null ? (rhrTrendLabel ? `bpm · ${rhrTrendLabel}` : 'bpm') : i18n._(msg`no data`)}</span></div>
        <div className="today-cell"><span className="today-cell-label"><Trans>Sleep</Trans></span><span className="today-cell-value font-data">{sleepScore != null ? Math.round(sleepScore) : '—'}</span><span className="today-cell-sub font-data">{sleepScore != null ? i18n._(msg`overnight score`) : i18n._(msg`no data`)}</span></div>
        {readinessScore != null && (
          <div className="today-cell"><span className="today-cell-label"><Trans>Readiness</Trans></span><span className="today-cell-value font-data">{Math.round(readinessScore)}</span><span className="today-cell-sub font-data"><Trans>daily score</Trans></span></div>
        )}
        <div className="today-cell"><span className="today-cell-label">TSB</span><span className={`today-cell-value font-data ${tsb > 0 ? 'today-cell-value-positive' : ''}`.trim()}>{tsbDisplay}</span><span className="today-cell-sub font-data">{tsbDescriptor}</span></div>
      </div>
      <div className="today-plan"><span className="today-plan-eyebrow"><Trans>Planned · Today</Trans></span><span className="today-plan-text">{planText}</span></div>
    </div>
  );
}
