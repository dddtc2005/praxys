import { useState, useEffect, useCallback, useMemo } from 'react';
import { useApi, API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { PlanResponse, PlannedWorkout, StrydPushStatus, StrydPushResult } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Trans, useLingui, Plural } from '@lingui/react/macro';
import { useLocale } from '@/contexts/LocaleContext';
import { useSettings } from '@/contexts/SettingsContext';

// Window pill choices for the Plan section. Days, not weeks, because
// the API speaks day-resolution and the user reads "next 14 days" the
// same way they read "two weeks." Persist the choice so power users
// land on their preferred view every visit.
const WINDOW_OPTIONS = [
  { id: '1wk', days: 7 },
  { id: '2wk', days: 14 },
  { id: '4wk', days: 28 },
] as const;
type WindowId = typeof WINDOW_OPTIONS[number]['id'];
const WINDOW_STORAGE_KEY = 'praxys.plan_window';

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function endIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

// Workout-type chips lean on the semantic palette only.
//   primary       — easy / recovery (action: go and run easy)
//   muted         — long (steady aerobic methodology slot, restrained)
//   accent-amber  — tempo / threshold (caution: at the line)
//   destructive   — interval / repetition (this costs you)
//   muted         — unknown types (no accent rather than reaching for blue/purple)
const TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  easy:       { bg: 'bg-primary/15',      text: 'text-primary' },
  recovery:   { bg: 'bg-primary/15',      text: 'text-primary' },
  long:       { bg: 'bg-muted',           text: 'text-foreground' },
  tempo:      { bg: 'bg-accent-amber/15', text: 'text-accent-amber' },
  threshold:  { bg: 'bg-accent-amber/15', text: 'text-accent-amber' },
  interval:   { bg: 'bg-destructive/15',  text: 'text-destructive' },
  repetition: { bg: 'bg-destructive/15',  text: 'text-destructive' },
};

const DEFAULT_COLOR = { bg: 'bg-muted', text: 'text-muted-foreground' };

function getTypeColor(type: string) {
  const key = type.toLowerCase().replace(/\s+/g, ' ');
  if (TYPE_COLORS[key]) return TYPE_COLORS[key];
  for (const [k, v] of Object.entries(TYPE_COLORS)) {
    if (key.includes(k)) return v;
  }
  return DEFAULT_COLOR;
}

function formatType(type: string): string {
  return type
    .split(/[\s_]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function formatDate(dateStr: string, locale: string): { day: string; weekday: string; isToday: boolean } {
  const d = new Date(dateStr + 'T00:00:00');
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isToday = d.getTime() === today.getTime();
  return {
    day: d.getDate().toString().padStart(2, '0'),
    weekday: d.toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US', { weekday: 'short' }).toUpperCase(),
    isToday,
  };
}

// Server-truth states (`pushed`, `mismatch`, `not_synced`, `native`) are
// merged with transient local states (`pushing`, `error`) to yield a
// single per-row badge state. The resolver in the parent picks one.
type PushState =
  | 'none'        // AI row, never pushed (sync_state='not_synced')
  | 'pushed'      // AI row, server says 'synced'
  | 'pushing'     // local optimistic — push request in flight
  | 'error'       // local optimistic — push request failed
  | 'mismatch'    // AI row + Stryd row exist but ids don't match
  | 'native';     // workout originated on Stryd (source='stryd')

const UploadIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M8 2v8M5 7l3-3 3 3M3 12h10" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const SpinnerIcon = ({ className }: { className?: string }) => (
  <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
);

const CheckIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 8.5l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const ErrorIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="currentColor">
    <path d="M8 1a7 7 0 100 14A7 7 0 008 1zM7 5h2v4H7V5zm0 5h2v2H7v-2z" />
  </svg>
);

const RefreshIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M2.5 8a5.5 5.5 0 019.3-4M13.5 8a5.5 5.5 0 01-9.3 4" strokeLinecap="round" />
    <path d="M12 1.5v3h-3M4 11.5v3h3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const WarningIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 16 16" fill="currentColor">
    <path d="M7.13 1.66a1 1 0 011.74 0l6.31 11.18A1 1 0 0114.31 14.5H1.69a1 1 0 01-.87-1.66L7.13 1.66zM7 6h2v4H7V6zm0 5h2v2H7v-2z" />
  </svg>
);

// Always-visible labeled pill for the per-row sync state. The earlier
// design hid action affordances behind hover (`group-hover:text-…`), so
// users on touch devices and anyone scanning the list at a glance had
// no way to see what to do — the only way to discover "push" was to
// hover every row. Showing the action explicitly trades a few px of
// horizontal space for a clearer single-click CTA.
const PILL_BASE =
  'inline-flex items-center gap-1.5 shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium ' +
  'transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const PILL_CLICKABLE = 'cursor-pointer';
const PILL_STATIC = 'cursor-default';

function StrydStatusBadge({
  state,
  error,
  onPush,
  showStryd,
}: {
  state: PushState;
  error?: string;
  onPush?: () => void;
  showStryd: boolean;
}) {
  const { t } = useLingui();
  if (!showStryd) return null;

  if (state === 'native') {
    return (
      <span
        className={`${PILL_BASE} ${PILL_STATIC} bg-muted text-muted-foreground`}
        title={t`This workout was imported from Stryd.`}
      >
        <Trans>From Stryd</Trans>
      </span>
    );
  }

  if (state === 'pushing') {
    return (
      <span className={`${PILL_BASE} ${PILL_STATIC} bg-accent-cobalt/10 text-accent-cobalt`}>
        <SpinnerIcon className="h-3 w-3" />
        <Trans>Syncing…</Trans>
      </span>
    );
  }

  if (state === 'error') {
    return (
      <button
        type="button"
        onClick={onPush}
        title={error || t`Push failed — click to retry`}
        aria-label={t`Retry push to Stryd`}
        className={`${PILL_BASE} ${PILL_CLICKABLE} bg-destructive/10 text-destructive hover:bg-destructive/15`}
      >
        <ErrorIcon className="h-3 w-3" />
        <Trans>Retry</Trans>
      </button>
    );
  }

  if (state === 'mismatch') {
    return (
      <button
        type="button"
        onClick={onPush}
        title={t`This workout differs on Stryd — click to overwrite with the Praxys version.`}
        aria-label={t`Overwrite Stryd with Praxys version`}
        className={`${PILL_BASE} ${PILL_CLICKABLE} bg-accent-amber/10 text-accent-amber hover:bg-accent-amber/15`}
      >
        <WarningIcon className="h-3 w-3" />
        <Trans>Differs · overwrite</Trans>
      </button>
    );
  }

  if (state === 'pushed') {
    // Synced — clicking re-pushes (after deleting the prior workout
    // server-side). Keep a soft hover state so the affordance is
    // discoverable without screaming for attention.
    return (
      <button
        type="button"
        onClick={onPush}
        title={t`Synced to Stryd. Click to re-push.`}
        aria-label={t`Re-push to Stryd`}
        className={`${PILL_BASE} ${PILL_CLICKABLE} bg-primary/10 text-primary hover:bg-primary/15 [&>svg.check]:inline [&>svg.refresh]:hidden hover:[&>svg.check]:hidden hover:[&>svg.refresh]:inline`}
      >
        <CheckIcon className="check h-3 w-3" />
        <RefreshIcon className="refresh h-3 w-3" />
        <Trans>Synced</Trans>
      </button>
    );
  }

  // state === 'none' — never pushed. The clear primary CTA: click to push.
  return (
    <button
      type="button"
      onClick={onPush}
      title={t`Push this workout to your Stryd calendar.`}
      aria-label={t`Push to Stryd`}
      className={`${PILL_BASE} ${PILL_CLICKABLE} bg-accent-cobalt/10 text-accent-cobalt hover:bg-accent-cobalt/20`}
    >
      <UploadIcon className="h-3 w-3" />
      <Trans>Sync to Stryd</Trans>
    </button>
  );
}

function WorkoutRow({
  workout,
  pushState,
  pushError,
  showStryd,
  onPushSingle,
}: {
  workout: PlannedWorkout;
  pushState: PushState;
  pushError?: string;
  showStryd: boolean;
  onPushSingle: (date: string) => void;
}) {
  const { t } = useLingui();
  const { locale } = useLocale();
  const { day, weekday, isToday } = formatDate(workout.date, locale);
  const color = getTypeColor(workout.workout_type);
  const isRest = workout.workout_type.toLowerCase() === 'rest';

  const details: string[] = [];
  if (workout.duration_min != null) details.push(`${Math.round(workout.duration_min)}m`);
  if (workout.distance_km != null) details.push(`${workout.distance_km}km`);
  if (workout.power_min != null && workout.power_max != null)
    details.push(`${workout.power_min}\u2013${workout.power_max}W`);

  return (
    <div
      className={`group flex items-center gap-3 py-2.5 px-3 rounded-lg transition-colors ${
        isToday
          ? 'bg-primary/5 ring-1 ring-primary/30'
          : 'hover:bg-muted/50'
      }`}
    >
      {/* Date column */}
      <div className="flex flex-col items-center w-10 shrink-0">
        <span className={`text-[10px] font-semibold tracking-wider ${
          isToday ? 'text-primary' : 'text-muted-foreground'
        }`}>
          {isToday ? t`TODAY` : weekday}
        </span>
        <span className={`font-data text-lg leading-tight ${
          isToday ? 'text-primary font-bold' : 'text-muted-foreground'
        }`}>
          {day}
        </span>
      </div>

      {/* Divider */}
      <div className={`w-px h-8 ${isToday ? 'bg-primary/30' : 'bg-border'}`} />

      {/* Type badge + details */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${color.bg} ${color.text}`}>
            {formatType(workout.workout_type)}
          </span>
          {details.length > 0 && (
            <span className="font-data text-xs text-muted-foreground truncate">
              {details.join(' · ')}
            </span>
          )}
        </div>
        {workout.description && (
          <p className="text-xs text-muted-foreground mt-0.5 truncate">{workout.description}</p>
        )}
      </div>

      {/* Stryd sync status / push button */}
      {!isRest && (
        <StrydStatusBadge
          state={pushState}
          error={pushError}
          showStryd={showStryd}
          onPush={() => onPushSingle(workout.date)}
        />
      )}
    </div>
  );
}

async function pushDatesToStryd(dates: string[]): Promise<{
  results: StrydPushResult[];
}> {
  const resp = await fetch(`${API_BASE}/api/plan/push-stryd`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() as Record<string, string> },
    body: JSON.stringify({ workout_dates: dates }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

function WindowPills({
  active,
  onChange,
}: {
  active: WindowId;
  onChange: (next: WindowId) => void;
}) {
  const { t } = useLingui();
  const labels: Record<WindowId, string> = {
    '1wk': t`1 wk`,
    '2wk': t`2 wk`,
    '4wk': t`4 wk`,
  };
  return (
    <div
      role="tablist"
      aria-label={t`Plan window`}
      className="inline-flex items-center gap-1 rounded-full bg-muted/60 p-1 text-[11px] font-medium"
    >
      {WINDOW_OPTIONS.map((opt) => {
        const isActive = opt.id === active;
        return (
          <button
            key={opt.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(opt.id)}
            className={`rounded-full px-3 py-1 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
              isActive
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {labels[opt.id]}
          </button>
        );
      })}
    </div>
  );
}

export default function UpcomingPlanCard() {
  const [windowId, setWindowId] = useState<WindowId>(() => {
    if (typeof window === 'undefined') return '2wk';
    const stored = window.localStorage.getItem(WINDOW_STORAGE_KEY) as WindowId | null;
    return stored && WINDOW_OPTIONS.some((o) => o.id === stored) ? stored : '2wk';
  });
  const windowDays = WINDOW_OPTIONS.find((o) => o.id === windowId)?.days ?? 14;

  // Window in the URL keeps queryKey-keyed cache entries distinct per
  // window, so toggling 1wk ↔ 4wk doesn't replay the wrong cached body.
  const planUrl = useMemo(
    () => `/api/plan?start=${todayIso()}&end=${endIso(windowDays)}`,
    [windowDays],
  );
  const { data, loading, error, refetch } = useApi<PlanResponse>(planUrl);

  const [pushStatus, setPushStatus] = useState<StrydPushStatus>({});
  const [pushErrors, setPushErrors] = useState<Record<string, string>>({});
  const [pushing, setPushing] = useState(false);
  const [pushingDates, setPushingDates] = useState<Set<string>>(new Set());

  // Stryd connection status — read from SettingsContext rather than firing
  // a second /api/settings request.
  const { config: settings } = useSettings();
  const hasStryd = Boolean(settings?.connections?.includes('stryd'));

  const handleWindowChange = useCallback((next: WindowId) => {
    setWindowId(next);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(WINDOW_STORAGE_KEY, next);
    }
  }, []);

  // Mirror server stryd_status into local state so push/delete handlers can
  // apply optimistic updates without waiting for a refetch; the next /api/plan
  // response resyncs us to the server view.
  useEffect(() => {
    if (data?.stryd_status) {
      setPushStatus(data.stryd_status);
    }
  }, [data?.stryd_status]);

  const getPushState = useCallback(
    (workout: PlannedWorkout): PushState => {
      const date = workout.date;
      if (pushingDates.has(date)) return 'pushing';
      if (pushErrors[date]) return 'error';
      // Stryd-source rows have no AI/Stryd sync question — they are
      // already on Stryd by definition.
      if (workout.source === 'stryd') return 'native';
      // Server-derived sync_state is the source of truth for AI rows.
      // The local `pushStatus` map only matters for optimistic updates
      // between a successful push and the next /api/plan refetch.
      if (workout.sync_state === 'mismatch') return 'mismatch';
      if (workout.sync_state === 'synced' || pushStatus[date]) return 'pushed';
      return 'none';
    },
    [pushingDates, pushErrors, pushStatus],
  );

  const handlePushResults = useCallback(
    (results: StrydPushResult[], dates: string[]) => {
      setPushStatus((prev) => {
        const next = { ...prev };
        for (const r of results) {
          if (r.status === 'success') {
            next[r.date] = {
              workout_id: r.workout_id,
              pushed_at: new Date().toISOString(),
              status: 'pushed',
            };
          }
        }
        return next;
      });

      setPushErrors((prev) => {
        const next = { ...prev };

        // Clear errors for dates we just retried
        for (const d of dates) delete next[d];

        for (const r of results) {
          if (r.status === 'success') {
            delete next[r.date];
          } else {
            next[r.date] = r.error;
          }
        }

        return next;
      });
    },
    [],
  );

  // Push a single workout (or re-push by deleting old one first).
  //
  // Edge case worth knowing: when re-pushing (existing workout_id), we
  // DELETE first, then POST. If the DELETE succeeds but the POST fails,
  // the user lands in ``error`` state with the prior workout already
  // gone from Stryd. Re-clicking is the correct recovery — the second
  // attempt skips the DELETE branch (pushStatus was cleared) and just
  // creates a fresh workout. The user's intent ("overwrite the Stryd
  // version with mine") is consistent across the failure modes; we
  // surface the partial failure via the error pill rather than try to
  // be clever about rolling back.
  const pushSingle = useCallback(
    async (date: string) => {
      if (pushingDates.has(date)) return;

      setPushingDates((prev) => new Set(prev).add(date));

      let deleted = false;
      try {
        // If already pushed, delete the old workout from Stryd first
        const existing = pushStatus[date];
        if (existing?.workout_id) {
          const resp = await fetch(`${API_BASE}/api/plan/stryd-workout/${existing.workout_id}`, { method: 'DELETE', headers: getAuthHeaders() });
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
          }
          deleted = true;
          setPushStatus((prev) => {
            const next = { ...prev };
            delete next[date];
            return next;
          });
        }

        const { results } = await pushDatesToStryd([date]);
        handlePushResults(results, [date]);
      } catch (e) {
        const baseMsg = e instanceof Error ? e.message : 'Push failed';
        setPushErrors((prev) => ({
          ...prev,
          [date]: deleted
            ? `${baseMsg} (the previous Stryd workout was deleted before the new one failed — click Sync to upload again)`
            : baseMsg,
        }));
      } finally {
        setPushingDates((prev) => {
          const next = new Set(prev);
          next.delete(date);
          return next;
        });
      }
    },
    [pushingDates, pushStatus, handlePushResults],
  );

  // Push all unpushed AI workouts. Mirrors the ``aiPushable`` filter
  // used to render the count beside the button — both must agree, or
  // the button will offer to push N rows then push N±k after a
  // round-trip. Specifically: must be ``source='ai'`` (Stryd-native
  // rows would create *duplicates* on Stryd if pushed back),
  // non-rest, and either not yet synced (``not_synced``) or diverged
  // (``mismatch`` — re-push to overwrite).
  const pushAll = useCallback(async () => {
    if (!data) return;

    const datesToPush = data.workouts
      .filter(
        (w) => w.source === 'ai'
          && w.workout_type.toLowerCase() !== 'rest'
          && (w.sync_state === 'not_synced' || w.sync_state === 'mismatch')
          && !pushStatus[w.date],
      )
      .map((w) => w.date);

    if (datesToPush.length === 0) return;

    setPushing(true);
    setPushingDates(new Set(datesToPush));
    setPushErrors({});

    try {
      const { results } = await pushDatesToStryd(datesToPush);
      handlePushResults(results, datesToPush);
    } catch (e) {
      const newErrors: Record<string, string> = {};
      for (const d of datesToPush) {
        newErrors[d] = e instanceof Error ? e.message : 'Push failed';
      }
      setPushErrors(newErrors);
    } finally {
      setPushing(false);
      setPushingDates(new Set());
    }
  }, [data, pushStatus, handlePushResults]);

  if (loading) {
    return (
      <section>
        <Skeleton className="h-3 w-32 mb-5" />
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm text-destructive"><Trans>Failed to load training plan</Trans></p>
          <p className="text-xs text-muted-foreground">{error}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
      </section>
    );
  }

  if (!data) return null;

  // Header chrome: eyebrow + window pills (left) and Push All + count
  // (right). Stays the same in empty / populated states so the user
  // can switch windows without the chrome jumping around.
  const aiPushable = data.workouts.filter(
    (w) => w.source === 'ai'
      && w.workout_type.toLowerCase() !== 'rest'
      && (w.sync_state === 'not_synced' || w.sync_state === 'mismatch')
      && !pushStatus[w.date],
  );
  const unpushedCount = aiPushable.length;
  const allSynced = unpushedCount === 0
    && data.workouts.some((w) => w.source === 'ai');

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
      <div className="flex items-center gap-3">
        <p className="text-[10px] font-data uppercase tracking-[0.14em] text-muted-foreground">
          <Trans>Upcoming Plan</Trans>
        </p>
        <WindowPills active={windowId} onChange={handleWindowChange} />
      </div>
      <div className="flex items-center gap-3">
        {data.workouts.length > 0 && (
          <span className="text-[11px] text-muted-foreground font-data">
            <Plural value={data.workouts.length} one="# workout" other="# workouts" />
          </span>
        )}
        {hasStryd && data.workouts.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-3 text-[11px] gap-1.5"
            disabled={pushing || allSynced}
            onClick={pushAll}
          >
            {pushing ? (
              <>
                <SpinnerIcon className="h-3 w-3" />
                <Trans>Pushing…</Trans>
              </>
            ) : allSynced ? (
              <>
                <CheckIcon className="h-3 w-3" />
                <Trans>All synced</Trans>
              </>
            ) : (
              <>
                <UploadIcon className="h-3 w-3" />
                <Trans>Push to Stryd</Trans>
                {unpushedCount > 0 && (
                  <span className="font-data ml-0.5">({unpushedCount})</span>
                )}
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );

  if (data.workouts.length === 0) {
    const widerHint = windowId !== '4wk'
      ? <Trans>Try a longer window above.</Trans>
      : null;
    return (
      <section>
        {header}
        <p className="text-sm text-muted-foreground">
          <Trans>No workouts scheduled in this window.</Trans>
          {widerHint && <span className="ml-1">{widerHint}</span>}
        </p>
      </section>
    );
  }

  return (
    <section>
      {header}
      <div className="space-y-1">
        {data.workouts.map((w) => (
          <WorkoutRow
            key={`${w.source}-${w.date}`}
            workout={w}
            pushState={getPushState(w)}
            pushError={pushErrors[w.date]}
            showStryd={hasStryd}
            onPushSingle={pushSingle}
          />
        ))}
      </div>
    </section>
  );
}
