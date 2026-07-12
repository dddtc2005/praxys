import { useEffect, useState } from 'react';
import { useApi, API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { RecoveryAnalysis, TodayResponse, TrainingSignal } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { msg } from '@lingui/core/macro';
import { Trans, useLingui } from '@lingui/react/macro';
import type { I18n, MessageDescriptor } from '@lingui/core';
import { useLocale } from '@/contexts/LocaleContext';
import AiInsightsCard, { type CoachFallback } from '@/components/AiInsightsCard';
import TodayDecisionCheck from '@/components/TodayDecisionCheck';
import ScienceNote from '@/components/ScienceNote';
import { recordProductEventOnce } from '@/lib/product-events';


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
  unscheduled: msg`NO PLAN`,
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
  unscheduled: msg`No Workout Scheduled`,
  easy: msg`Go Easy`,
  modify: msg`Adjust Workout`,
  reduce_intensity: msg`Reduce Intensity`,
  rest: msg`Recovery Day`,
};

type SignalTone = 'green' | 'amber' | 'red';

const VERDICT_TONE: Record<TrainingSignal['recommendation'], SignalTone> = {
  follow_plan: 'green',
  unscheduled: 'amber',
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
  improving: msg`rising`,
  declining: msg`falling`,
};

const RHR_TREND_LABEL: Record<'stable' | 'elevated' | 'low', MessageDescriptor> = {
  stable: msg`near baseline`,
  elevated: msg`above baseline`,
  low: msg`below baseline`,
};

// ESTIMATE: Praxys display labels for modeled training stress balance (TSB).
// Banister motivates the load model, but does not validate these product bands.
//   ≥ +10  positive balance
//   0..10  slightly positive
//   -10..0 slightly negative
//   < -10  negative balance
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

// Attach each recovery metric to its own source observation date.
function formatMetricProvenance(
  isoDate: string | null | undefined,
  locale: string,
  i18n: I18n,
): string | null {
  if (!isoDate) return null;
  const label = formatIsoDateShort(isoDate, locale);
  return i18n._(msg`from ${label}`);
}

// Format data_as_of for the staleness banner in the user's local time.
function formatDataAsOf(iso: string, locale: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit',
  });
}

// Treat a prior-date snapshot as stale unless it contains a recovery reading
// that the server still considers current. Sleep/HRV is commonly recorded
// under the night it describes, so yesterday's row has a deliberate one-day
// grace and must not disable today's decision check.
function isDataStale(
  dataAsOf: string | null | undefined,
  recovery: RecoveryAnalysis | null | undefined,
): boolean {
  if (!dataAsOf) return false;
  const d = new Date(dataAsOf);
  if (Number.isNaN(d.getTime())) return false;
  const dataLocalDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const now = new Date();
  const todayLocalDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  if (dataLocalDate >= todayLocalDate) return false;
  return !recovery?.latest_date || recovery.is_stale;
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

function localizedSignalReason(signal: TrainingSignal, i18n: I18n): string {
  const rawTsb = signal.reason_args?.tsb ?? signal.recovery.tsb;
  const tsb = rawTsb == null ? '' : Number(rawTsb).toFixed(0);
  const cv = Number(signal.reason_args?.cv ?? 0).toFixed(0);
  const sleep = Number(signal.reason_args?.sleep ?? 0).toFixed(0);

  switch (signal.reason_code) {
    case 'unscheduled_hrv_caution':
      return i18n._(msg`No workout is scheduled, and HRV is below your personal caution band. Keep the day restorative rather than adding a hard session.`);
    case 'unscheduled_high_load':
      return i18n._(msg`No workout is scheduled, and modeled load balance is low (TSB ${tsb}). Avoid adding intensity today.`);
    case 'unscheduled_open':
      return i18n._(msg`No workout is scheduled. Add a session only if it fits your broader plan.`);
    case 'rest_scheduled':
      return i18n._(msg`Rest day scheduled. Follow the plan and prioritize recovery.`);
    case 'hrv_stale':
      return i18n._(msg`The latest HRV reading is out of date. Follow the plan without an HRV-based recovery adjustment.`);
    case 'hrv_zero_variance':
      return i18n._(msg`Recent HRV observations have no measurable variation, so Praxys cannot form a reliable recovery band yet. Follow the plan without an HRV-based adjustment.`);
    case 'hrv_history_insufficient':
      return i18n._(msg`More historical HRV observations are needed before Praxys can form a personal recovery band. Follow the plan without an HRV-based adjustment.`);
    case 'hrv_unavailable':
      return i18n._(msg`Recovery requires current HRV data. Connect or sync an HRV-capable device to receive recovery suggestions.`);
    case 'hrv_below_hard':
      return i18n._(msg`HRV is below your personal caution band. Treat this as a recovery signal, not a diagnosis.`);
    case 'hrv_below_easy':
      return i18n._(msg`HRV is below your personal caution band. Keep today easy to support recovery.`);
    case 'high_load_hard':
      return i18n._(msg`HRV is within your personal reference band, but modeled load balance is low (TSB ${tsb}). Modify the hard session.`);
    case 'hrv_declining_hard':
      return i18n._(msg`HRV rolling mean is lower than its prior window. Reduce intensity as a conservative coaching adjustment.`);
    case 'hrv_declining_easy':
      return i18n._(msg`HRV rolling mean is lower than its prior window. Stay easy today.`);
    case 'hrv_variability_high':
      return i18n._(msg`HRV variability is high (CV ${cv}%), above the selected coaching caution threshold.`);
    case 'sleep_low_hard':
      return i18n._(msg`Sleep score is low (${sleep}). Consider reducing today's intensity.`);
    case 'resting_hr_elevated_hard':
      return i18n._(msg`Resting heart rate is elevated above your baseline. This can be a caution signal, but it is not diagnostic.`);
    case 'hrv_above_baseline':
      return i18n._(msg`HRV is above your personal reference band. Follow the plan as written.`);
    case 'recovery_normal':
      return i18n._(msg`Recovery signals are within their recent reference bands. Follow the plan as written.`);
    default:
      return signal.reason;
  }
}

function localizedSignalAlternatives(signal: TrainingSignal, i18n: I18n): string[] {
  if (!signal.alternative_codes?.length) return signal.alternatives;

  return signal.alternative_codes.map((item, index) => {
    const workout = String(item.args.workout ?? signal.plan.workout_type ?? '');
    switch (item.code) {
      case 'restorative_movement':
        return i18n._(msg`Rest, walk, or do gentle mobility`);
      case 'optional_easy_short':
        return i18n._(msg`Keep any optional movement easy and short`);
      case 'full_recovery_reassess':
        return i18n._(msg`Make today a full recovery day and reassess the hard session tomorrow`);
      case 'drop_to_easy':
        return i18n._(msg`Drop to easy run (keep power in recovery zone)`);
      case 'push_to_tomorrow_if_easy':
        return i18n._(msg`Push ${workout} to tomorrow if tomorrow is rest/easy`);
      case 'cap_low_power':
        return i18n._(msg`Run as planned but cap at low end of power range`);
      case 'swap_for_easy':
        return i18n._(msg`Swap ${workout} for easy run`);
      case 'drop_one_zone':
        return i18n._(msg`Drop intensity by one zone`);
      case 'push_to_tomorrow':
        return i18n._(msg`Push ${workout} to tomorrow`);
      case 'proceed_monitor_body':
        return i18n._(msg`Run as planned but monitor how you feel`);
      case 'shorten_if_fatigued':
        return i18n._(msg`Shorten the session if fatigue develops`);
      case 'run_easy':
        return i18n._(msg`Run easy instead`);
      case 'monitor_hr_drift':
        return i18n._(msg`Proceed but monitor heart-rate drift during the session`);
      default:
        return signal.alternatives[index] ?? '';
    }
  }).filter(Boolean);
}
export default function Today() {
  const { data, loading, error, refetch } = useApi<TodayResponse>('/api/today', {
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
  });
  const { locale } = useLocale();
  const { i18n } = useLingui();

  // Page-level data-staleness state. ``dismissed`` is the "Show anyway"
  // escape hatch — component-scoped (not localStorage) so each fresh
  // page load re-prompts. ``syncing`` flips while a manual sync is
  // running so the button can render a loading state without blocking
  // the rest of the page.
  const [dismissed, setDismissed] = useState(false);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    if (!data?.as_of_date) return undefined;
    const recordWhenVisible = () => {
      if (document.visibilityState === 'visible') {
        recordProductEventOnce('today_brief_rendered', data.as_of_date);
      }
    };
    recordWhenVisible();
    document.addEventListener('visibilitychange', recordWhenVisible);
    return () => document.removeEventListener('visibilitychange', recordWhenVisible);
  }, [data?.as_of_date]);

  if (loading) return <TodaySkeleton />;

  if (error && !data) {
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
  const localizedReason = localizedSignalReason(signal, i18n);
  const localizedAlternatives = localizedSignalAlternatives(signal, i18n);

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
  const hrv = ra?.hrv ?? null;
  const trendArrow = hrv ? TREND_ARROW[hrv.trend] : '—';
  const trendLabel = hrv ? i18n._(HRV_TREND_LABEL[hrv.trend]) : '—';
  const trendCv = hrv != null ? `${hrv.rolling_cv.toFixed(1)}%` : '—';
  // Only show an RHR baseline comparison when the API actually emits one.
  const rhrTrendLabel = ra?.rhr_trend ? i18n._(RHR_TREND_LABEL[ra.rhr_trend]) : null;
  const baselineLabel = hrv ? i18n._(msg`vs ${hrv.baseline_mean_ln.toFixed(2)} baseline`) : i18n._(msg`no data`);
  const hrvDateLabel = formatMetricProvenance(ra?.hrv_latest_date, locale, i18n);
  const sleepScore = ra?.sleep_score;
  const sleepDateLabel = formatMetricProvenance(ra?.sleep_latest_date, locale, i18n);
  const readinessScore = ra?.readiness_score;
  const readinessDateLabel = formatMetricProvenance(ra?.readiness_latest_date, locale, i18n);
  const observationCount = data.recovery_theory?.params.rolling_days ?? 7;
  const restingHr = ra?.resting_hr;
  const rhrDateLabel = formatMetricProvenance(ra?.rhr_latest_date, locale, i18n);
  const rhrDisplay = restingHr != null ? Math.round(restingHr) : '—';
  const hrvSub = hrv
    ? [hrv.today_ms != null ? `${hrv.today_ms} ms` : null, baselineLabel, hrvDateLabel]
        .filter(Boolean).join(' · ')
    : i18n._(msg`no data`);
  const rhrSub = restingHr != null
    ? ['bpm', rhrTrendLabel, rhrDateLabel].filter(Boolean).join(' · ')
    : i18n._(msg`no data`);
  const sleepSub = sleepScore != null
    ? [i18n._(msg`overnight score`), sleepDateLabel].filter(Boolean).join(' · ')
    : i18n._(msg`no data`);
  const readinessSub = readinessScore != null
    ? [i18n._(msg`daily score`), readinessDateLabel].filter(Boolean).join(' · ')
    : i18n._(msg`no data`);
  const tsb = signal.recovery.tsb;
  const tsbDisplay = tsb == null
    ? '—'
    : `${tsb >= 0 ? '+' : ''}${tsb.toFixed(1)}`;
  const tsbDescriptorMsg = tsb == null
    ? msg`not enough load history`
    : tsb >= TSB_STRONGLY_POSITIVE ? msg`positive balance`
    : tsb > 0 ? msg`slightly positive`
    : tsb > TSB_MILD_FATIGUE ? msg`slightly negative`
    : msg`negative balance`;
  const tsbDescriptor = i18n._(tsbDescriptorMsg);
  const planText = formatPlan(signal.plan) ?? i18n._(msg`No workout scheduled.`);

  // Theory attribution for the deterministic Coach receipt and methodology.
  // It follows the user's active recovery and load theories instead of
  // hard-coding the default Plews/Banister pair.
  const recoveryNote = data.science_notes?.recovery;
  const loadNote = data.science_notes?.load;
  const recoveryNoteName = recoveryNote?.name;
  const loadNoteName = loadNote?.name;
  const attribution = [recoveryNoteName, loadNoteName].filter(Boolean).join(' · ');
  const methodologySources = [
    recoveryNote?.citations?.[0],
    loadNote?.citations?.[0],
  ].filter((citation): citation is { label: string; url: string } => Boolean(citation?.url));
  const methodologyText = i18n._(msg`Today's recommendation combines the scheduled workout with Praxys operational adaptations of your active recovery and load models. HRV requires a current reading, while TSB is modeled load balance rather than a direct measure of fatigue. Praxys TSB display labels and the one-CTL-window history gate are operational estimates, not validated cutoffs. These coaching guardrails are not a medical diagnosis.`);

  // Page-level data-staleness anchors on source measurements rather than
  // sync or AI-generation time. Yesterday's overnight recovery remains
  // current under the server's one-day grace; older snapshots still show
  // the general banner and suppress the recovery-only warning.
  const dataStale = isDataStale(data.data_as_of, ra);
  const hasDecisionContext = (
    data.data_as_of != null || Boolean(signal.plan?.workout_type)
  );
  const dataAsOfLabel = data.data_as_of ? formatDataAsOf(data.data_as_of, locale) : null;
  const showStaleBanner = dataStale && !!dataAsOfLabel && !dismissed;
  const showStaleChip = dataStale && !!dataAsOfLabel && dismissed;
  const showRecoveryBanner = !dataStale && recoveryStale && !!recoveryLatestLabel;

  // Manual sync — kicks the existing /api/sync route (background
  // tasks) and polls /api/sync/status until no source is still
  // ``syncing``. A bare ``setTimeout(6s)`` would re-enable the button
  // before Garmin's first-time fetch (30+ seconds for the initial
  // backfill) finishes; the user would see the button bounce back to
  // ``Sync now``, click again, and double-trigger. The five-minute wall
  // covers the two sequential insight-generation calls; beyond that
  // we refetch anyway and let the
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
      const deadline = Date.now() + 300_000;
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
      {error && (
        <Alert variant="destructive" className="today-refresh-error">
          <AlertTitle><Trans>Refresh failed</Trans></AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-3">
            <span><Trans>Showing the last available data.</Trans></span>
            <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
          </AlertDescription>
        </Alert>
      )}
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
      </div>
      {/* Praxys Coach receipt is deterministic on Today. The daily insight
          slot is intentionally disabled so generated prose can never
          contradict the canonical signal. */}
      <AiInsightsCard
        insightType="daily_brief"
        fetchInsight={false}
        attribution={attribution}
        fallback={{
          headline: localizedReason,
          recommendations: localizedAlternatives,
        } as CoachFallback}
        onDetailsOpen={() => recordProductEventOnce(
          'today_reasoning_opened',
          data.as_of_date,
        )}
      />
      <div className={`today-supporting ${readinessScore != null ? 'today-supporting--6' : ''}`.trim()}>
        <div className="today-cell"><span className="today-cell-label">HRV (ln RMSSD)</span><span className="today-cell-value font-data">{hrv ? hrv.today_ln.toFixed(2) : '—'}</span><span className="today-cell-sub font-data">{hrvSub}</span></div>
        <div className="today-cell"><span className="today-cell-label"><Trans>{observationCount}-observation Trend</Trans></span><span className="today-cell-value font-data">{trendArrow}</span><span className="today-cell-sub font-data">{hrv ? `${trendLabel} · CV ${trendCv}` : i18n._(msg`no data`)}</span></div>
        <div className="today-cell"><span className="today-cell-label"><Trans>RHR</Trans></span><span className="today-cell-value font-data">{rhrDisplay}</span><span className="today-cell-sub font-data">{rhrSub}</span></div>
        <div className="today-cell"><span className="today-cell-label"><Trans>Sleep</Trans></span><span className="today-cell-value font-data">{sleepScore != null ? Math.round(sleepScore) : '—'}</span><span className="today-cell-sub font-data">{sleepSub}</span></div>
        {readinessScore != null && (
          <div className="today-cell"><span className="today-cell-label"><Trans>Readiness</Trans></span><span className="today-cell-value font-data">{Math.round(readinessScore)}</span><span className="today-cell-sub font-data">{readinessSub}</span></div>
        )}
        <div className="today-cell"><span className="today-cell-label">TSB</span><span className={`today-cell-value font-data ${tsb != null && tsb > 0 ? 'today-cell-value-positive' : ''}`.trim()}>{tsbDisplay}</span><span className="today-cell-sub font-data">{tsbDescriptor}</span></div>
      </div>
      <div className="today-plan"><span className="today-plan-eyebrow"><Trans>Planned · Today</Trans></span><span className="today-plan-text">{planText}</span></div>
      <div className="today-methodology">
        <ScienceNote
          text={methodologyText}
          sources={methodologySources}
        />
      </div>
      {hasDecisionContext && !dataStale && !recoveryStale && (
        <TodayDecisionCheck key={data.as_of_date} />
      )}
    </div>
  );
}
