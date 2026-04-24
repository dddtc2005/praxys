import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useSettings } from '@/contexts/SettingsContext';
import { useSetupStatus } from '@/hooks/useSetupStatus';
import { API_BASE, getAuthHeaders, extractErrorMessage } from '@/hooks/useApi';
import type { TrainingBase, SyncStatusResponse } from '@/types/api';
import {
  buildStravaReturnTo,
  getStravaOAuthMessage,
  getStravaOAuthResult,
  startStravaOAuth,
  stripStravaOAuthParams,
} from '@/lib/strava-oauth';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { Check, Link2, RefreshCw, Gauge, Target, ChevronRight, Sparkles } from 'lucide-react';
import GoalEditor from '@/components/GoalEditor';
import { Trans, Plural, useLingui } from '@lingui/react/macro';
import { GarminWordmark, StrydWordmark, StravaWordmark, OuraWordmark } from '@/components/PlatformWordmark';

// --- Platform metadata ---

/**
 * Garmin activity type categories. Each category maps to multiple Garmin
 * API activitytype values. Selecting "Running" syncs all running subtypes.
 *
 * Display labels are resolved at render time via `localizedActivityLabel`
 * so they follow the user's Lingui locale.
 */
const GARMIN_ACTIVITY_CATEGORIES = [
  {
    key: 'running',
    default: true,
    types: ['running', 'trail_running', 'treadmill_running', 'track_running', 'ultra_running', 'indoor_running'],
  },
  {
    key: 'cycling',
    default: false,
    types: ['cycling', 'mountain_biking', 'indoor_cycling'],
  },
  {
    key: 'swimming',
    default: false,
    types: ['swimming', 'open_water_swimming', 'lap_swimming'],
  },
  {
    key: 'hiking',
    default: false,
    types: ['hiking'],
  },
  {
    key: 'walking',
    default: false,
    types: ['walking'],
  },
  {
    key: 'strength',
    default: false,
    types: ['strength_training'],
  },
] as const;

const PLATFORM_META: Record<string, {
  label: string;
  wordmark: React.ReactNode;
  /** Which data categories this platform provides (only list supported ones). */
  categories: string[];
  detail: string;
  credFields: { key: string; label: string; type: string }[];
  help: string;
}> = {
  garmin: {
    label: 'Garmin',
    wordmark: <GarminWordmark />,
    categories: ['Activities', 'Recovery', 'Fitness'],
    detail: 'HR, pace, distance, VO2max, training status',
    credFields: [
      { key: 'email', label: 'Email', type: 'email' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
    help: 'Use your Garmin Connect credentials.',
  },
  strava: {
    label: 'Strava',
    wordmark: <StravaWordmark />,
    categories: ['Activities'],
    detail: 'Activities only: runs, rides, pace, heart rate, route data',
    credFields: [],
    help: 'Authorize Praxys with Strava in your browser. Praxys only syncs activities from Strava.',
  },
  stryd: {
    label: 'Stryd',
    wordmark: <StrydWordmark />,
    categories: ['Activities', 'Fitness', 'Plan'],
    detail: 'Power metrics, Critical Power, training plans',
    credFields: [
      { key: 'email', label: 'Email', type: 'email' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
    help: 'Use your Stryd account credentials (stryd.com).',
  },
  oura: {
    label: 'Oura Ring',
    wordmark: <OuraWordmark />,
    categories: ['Recovery'],
    detail: 'Sleep score, HRV, readiness',
    credFields: [
      { key: 'token', label: 'Personal Access Token', type: 'password' },
    ],
    help: 'Generate a token at cloud.ouraring.com/personal-access-tokens.',
  },
};

const CONNECTABLE_PLATFORMS = ['garmin', 'strava', 'stryd', 'oura'] as const;


// Training-base keys used by `BASE_CONFIG` below. Display labels come from
// the Lingui catalog at render time (see `getBaseConfig`).
const TRAINING_BASE_KEYS: TrainingBase[] = ['power', 'hr', 'pace'];

// Backfill range options. `days` is canonical; `label` is localized at
// render time (see `getBackfillOptions`).
const BACKFILL_DAYS = [
  { days: 30 },
  { days: 90 },
  { days: 180, recommended: true },
  { days: 365 },
] as const;

// --- Component ---

export default function Setup() {
  const location = useLocation();
  const navigate = useNavigate();
  const { config, updateSettings, refetch: refetchSettings } = useSettings();
  const setup = useSetupStatus();
  const { t } = useLingui();

  const activityCategoryLabel = (key: string): string => {
    switch (key) {
      case 'running': return t`Running`;
      case 'cycling': return t`Cycling`;
      case 'swimming': return t`Swimming`;
      case 'hiking': return t`Hiking`;
      case 'walking': return t`Walking`;
      case 'strength': return t`Strength`;
      default: return key;
    }
  };
  const baseInfo = (base: TrainingBase): { label: string; desc: string } => {
    switch (base) {
      case 'power':
        return { label: t`Power`, desc: t`Zones & load from Critical Power (best with Stryd)` };
      case 'hr':
        return { label: t`Heart Rate`, desc: t`Zones & load from Lactate Threshold HR` };
      case 'pace':
        return { label: t`Pace`, desc: t`Zones & load from Threshold Pace` };
    }
  };
  const backfillLabel = (days: number): string => {
    switch (days) {
      case 30: return t`1 month`;
      case 90: return t`3 months`;
      case 180: return t`6 months`;
      case 365: return t`1 year`;
      default: return `${days} days`;
    }
  };
  const platformDetail = (platform: string): string => {
    switch (platform) {
      case 'garmin': return t`HR, pace, distance, VO2max, training status`;
      case 'strava': return t`Activities only: runs, rides, pace, heart rate, route data`;
      case 'stryd': return t`Power metrics, Critical Power, training plans`;
      case 'oura': return t`Sleep score, HRV, readiness`;
      default: return PLATFORM_META[platform]?.detail ?? '';
    }
  };
  const platformHelp = (platform: string): string => {
    switch (platform) {
      case 'garmin': return t`Use your Garmin Connect credentials.`;
      case 'strava': return t`Authorize Praxys with Strava in your browser. Praxys only syncs activities from Strava.`;
      case 'stryd': return t`Use your Stryd account credentials (stryd.com).`;
      case 'oura': return t`Generate a token at cloud.ouraring.com/personal-access-tokens.`;
      default: return PLATFORM_META[platform]?.help ?? '';
    }
  };
  const credFieldLabel = (key: string, fallback: string): string => {
    switch (key) {
      case 'email': return t`Email`;
      case 'password': return t`Password`;
      case 'token': return t`Personal Access Token`;
      default: return fallback;
    }
  };
  const platformCategoryLabel = (category: string): string => {
    // Display labels for data-provider categories on platform cards.
    switch (category) {
      case 'Activities': return t`Activities`;
      case 'Recovery': return t`Recovery`;
      case 'Fitness': return t`Fitness`;
      case 'Plan': return t`Plan`;
      default: return category;
    }
  };

  // Connection state
  const [connectPlatform, setConnectPlatform] = useState<string | null>(null);
  const [connectCreds, setConnectCreds] = useState<Record<string, string>>({});
  const [connectError, setConnectError] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [connectNotice, setConnectNotice] = useState('');
  const [pendingPrimaryPlatform, setPendingPrimaryPlatform] = useState<string | null>(null);
  const [selectedCategories, setSelectedCategories] = useState<string[]>(
    GARMIN_ACTIVITY_CATEGORIES.filter((c) => c.default).map((c) => c.key)
  );
  const [garminRegion, setGarminRegion] = useState<'international' | 'cn'>('international');

  // Primary source prompt — shown when connecting a second source for same category
  const [primaryPrompt, setPrimaryPrompt] = useState<{
    category: string;
    options: string[];
  } | null>(null);

  // Sync state
  const [syncing, setSyncing] = useState(false);
  const [syncDone, setSyncDone] = useState(false);
  const [syncKickoffError, setSyncKickoffError] = useState('');
  const [backfillDays, setBackfillDays] = useState(180);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [liveSyncStatus, setLiveSyncStatus] = useState<SyncStatusResponse>({});

  // Goal state
  const [goalEditorOpen, setGoalEditorOpen] = useState(false);

  // Redirect when all done
  useEffect(() => {
    if (!setup.loading && setup.allDone) {
      navigate('/today', { replace: true });
    }
  }, [setup.loading, setup.allDone, navigate]);

  useEffect(() => {
    const oauthResult = getStravaOAuthResult(location.search);
    if (!oauthResult) return;

    const cleanedLocation = `${location.pathname}${stripStravaOAuthParams(location.search)}${location.hash}`;
    navigate(cleanedLocation, { replace: true });

    if (oauthResult.status === 'connected') {
      setConnectPlatform(null);
      setConnectCreds({});
      setConnectError('');
      setConnectNotice(getStravaOAuthMessage(oauthResult));
      setPendingPrimaryPlatform('strava');
      setup.refetch();
      refetchSettings();
      return;
    }

    setConnectNotice('');
    setConnectPlatform('strava');
    setConnectError(getStravaOAuthMessage(oauthResult));
  }, [location.hash, location.pathname, location.search, navigate, refetchSettings]);

  useEffect(() => {
    if (pendingPrimaryPlatform !== 'strava') return;
    if (!setup.connectedPlatforms.includes('strava')) return;

    const overlapping = setup.connectedPlatforms.filter(
      (platform) => platform !== 'strava' && PLATFORM_META[platform]?.categories.includes('Activities')
    );

    if (overlapping.length > 0) {
      setPrimaryPrompt({
        category: 'activities',
        options: ['strava', ...overlapping],
      });
    }

    setPendingPrimaryPlatform(null);
  }, [pendingPrimaryPlatform, setup.connectedPlatforms]);

  // Poll sync status while syncing
  useEffect(() => {
    if (syncing && !pollRef.current) {
      pollRef.current = setInterval(() => {
        fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() })
          .then((r) => r.json())
          .then((data: SyncStatusResponse) => {
            setLiveSyncStatus(data);
            const stillSyncing = Object.values(data).some((s) => s.status === 'syncing');
            if (!stillSyncing) {
              setSyncing(false);
              setSyncDone(true);
              if (pollRef.current) clearInterval(pollRef.current);
              pollRef.current = null;
              setup.refetch();
              refetchSettings();
            }
          })
          .catch(() => {});
      }, 2000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [syncing, setup, refetchSettings]);

  // Suggest training base — priority: stryd (power) > garmin (hr) > oura (hr)
  const suggestedBase: TrainingBase | null = (() => {
    const platforms = setup.connectedPlatforms;
    if (platforms.includes('stryd')) return 'power';
    if (platforms.includes('garmin')) return 'hr';
    if (platforms.includes('strava')) return 'pace';
    if (platforms.includes('oura')) return 'hr';
    return null;
  })();

  if (setup.loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-48 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
    );
  }

  const handleConnect = async () => {
    if (!connectPlatform) return;
    setConnecting(true);
    setConnectError('');
    setConnectNotice('');

    if (connectPlatform === 'strava') {
      try {
        await startStravaOAuth(buildStravaReturnTo(location.pathname, location.search, location.hash));
      } catch (err) {
        setConnectError(err instanceof Error ? err.message : 'Network error');
        setConnecting(false);
      }
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/settings/connections/${connectPlatform}`, {
        method: 'POST',
        headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...connectCreds,
          ...(connectPlatform === 'garmin' ? { is_cn: garminRegion === 'cn' } : {}),
        }),
      });
      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        setConnectError(data.message || `Failed to connect (HTTP ${res.status})`);
      } else {
        // Save Garmin-specific options
        if (connectPlatform === 'garmin') {
          // Expand selected categories into individual Garmin API types
          const activityTypes = GARMIN_ACTIVITY_CATEGORIES
            .filter((c) => selectedCategories.includes(c.key))
            .flatMap((c) => c.types as unknown as string[]);
          await updateSettings({
            source_options: {
              ...config?.source_options,
              garmin_region: garminRegion,
              garmin_activity_types: activityTypes,
              garmin_activity_categories: selectedCategories,
            },
          });
        }
        const justConnected = connectPlatform;
        setConnectPlatform(null);
        setConnectCreds({});
        setup.refetch();
        refetchSettings();

        // Check if another platform provides the same category — prompt for primary
        const newCategories = PLATFORM_META[justConnected]?.categories || [];
        const overlapping: string[] = [];
        for (const cat of newCategories) {
          const otherProviders = setup.connectedPlatforms
            .filter((p) => p !== justConnected && PLATFORM_META[p]?.categories.includes(cat));
          if (otherProviders.length > 0) {
            overlapping.push(cat);
          }
        }
        if (overlapping.length > 0) {
          // Show primary source prompt for the first overlapping category
          const cat = overlapping[0];
          const allProviders = [justConnected, ...setup.connectedPlatforms.filter(
            (p) => p !== justConnected && PLATFORM_META[p]?.categories.includes(cat)
          )];
          setPrimaryPrompt({ category: cat.toLowerCase(), options: allProviders });
        }
      }
    } catch {
      setConnectError('Network error');
    }
    setConnecting(false);
  };

  const abortKickoff = (message: string) => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setSyncKickoffError(message);
    setSyncing(false);
  };

  const handleSync = async () => {
    const fromDate = new Date();
    fromDate.setDate(fromDate.getDate() - backfillDays);
    const from = fromDate.toISOString().slice(0, 10);

    setSyncing(true);
    setSyncDone(false);
    setSyncKickoffError('');
    setLiveSyncStatus({});
    try {
      const res = await fetch(`${API_BASE}/api/sync`, {
        method: 'POST',
        headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_date: from }),
      });
      if (!res.ok) {
        abortKickoff(await extractErrorMessage(res, `Failed to start sync (HTTP ${res.status})`));
        return;
      }
      // No connected sources → backend happily returns 200 with sources:[]. Without
      // this guard the poller sees nothing-syncing immediately and falsely renders
      // "Sync complete!" — the exact class of silent success this PR exists to kill.
      const body = await res.json().catch(() => null);
      const sources = Array.isArray(body?.sources) ? body.sources : null;
      if (sources && sources.length === 0) {
        abortKickoff('No connected sources to sync. Connect a platform first.');
        return;
      }
      // Polling takes over from here
    } catch (err) {
      abortKickoff(err instanceof Error && err.message ? err.message : 'Network error');
    }
  };

  const handleBaseChange = async (base: TrainingBase) => {
    await updateSettings({ training_base: base });
  };

  const handleGoalSave = async (goal: { race_date: string; distance: string; target_time_sec: number }) => {
    await updateSettings({ goal });
    setup.refetch();
  };

  const progressPct = (setup.completed / setup.total) * 100;

  // Estimate sync time (rough: ~0.5s per activity for splits, assume ~3 activities/week)
  const estimatedActivities = Math.round((backfillDays / 7) * 3);
  const estimatedMinutes = Math.max(1, Math.round((estimatedActivities * 0.5 + 30) / 60));

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground"><Trans>Set up Praxys</Trans></h1>
        <p className="text-sm text-muted-foreground mt-1">
          {setup.completed === 0
            ? <Trans>Complete these steps to unlock your training insights</Trans>
            : <Trans>{setup.completed} of {setup.total} steps complete</Trans>}
        </p>

        {/* Progress bar */}
        <div className="h-1.5 w-full rounded-full bg-muted mt-4">
          <div
            className="h-1.5 rounded-full bg-primary transition-all duration-500 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        {connectNotice && (
          <Alert className="mt-4 border-primary/30 bg-primary/5">
            <AlertDescription className="text-sm text-primary">{connectNotice}</AlertDescription>
          </Alert>
        )}
      </div>

      <div className="space-y-4">
        {/* ===== STEP 1: Connect ===== */}
        <SetupCard
          stepNum={1}
          title={t`Connect a platform`}
          description={t`Link at least one data source to start`}
          done={setup.hasConnection}
          icon={<Link2 className="h-4 w-4" />}
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 mt-4">
            {CONNECTABLE_PLATFORMS.map((platform) => {
              const meta = PLATFORM_META[platform];
              const isConnected = setup.connectedPlatforms.includes(platform);
              return (
                <button
                  key={platform}
                  onClick={() => {
                    if (!isConnected) {
                      setConnectPlatform(platform);
                      setConnectCreds({});
                      setConnectError('');
                    }
                  }}
                  disabled={isConnected}
                  className={`rounded-xl p-4 text-left transition-all border ${
                    isConnected
                      ? 'border-primary/30 bg-primary/5'
                      : 'border-border hover:border-primary/40 hover:bg-muted/50'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="h-6 flex items-center">{meta.wordmark}</div>
                    {isConnected && <Check className="h-4 w-4 text-primary" />}
                  </div>
                  <p className="text-[11px] text-muted-foreground mb-2">{platformDetail(platform)}</p>
                  <div className="flex flex-wrap gap-1">
                    {meta.categories.map((cat) => (
                      <span
                        key={cat}
                        className="text-[10px] text-muted-foreground bg-muted rounded px-1.5 py-0.5"
                      >
                        {platformCategoryLabel(cat)}
                      </span>
                    ))}
                  </div>
                  {!isConnected && (
                    <p className="text-xs text-primary mt-3 font-medium"><Trans>Connect</Trans></p>
                  )}
                </button>
              );
            })}
          </div>
        </SetupCard>

        {/* ===== STEP 2: Sync ===== */}
        <SetupCard
          stepNum={2}
          title={t`Sync your data`}
          description={
            !setup.hasConnection
              ? t`Connect a platform first`
              : t`Choose how much historical data to pull`
          }
          done={setup.hasSyncedData}
          icon={<RefreshCw className="h-4 w-4" />}
          disabled={!setup.hasConnection}
        >
          {setup.hasConnection && !setup.hasSyncedData && (
            <div className="mt-4 space-y-4">
              {/* Backfill range */}
              <div>
                <Label className="text-xs text-muted-foreground mb-2 block"><Trans>Sync history</Trans></Label>
                <div className="flex flex-wrap gap-2">
                  {BACKFILL_DAYS.map((opt) => (
                    <button
                      key={opt.days}
                      onClick={() => setBackfillDays(opt.days)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all border ${
                        backfillDays === opt.days
                          ? 'border-primary/40 bg-primary/10 text-primary'
                          : 'border-transparent bg-muted text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {backfillLabel(opt.days)}
                      {'recommended' in opt && opt.recommended && (
                        <Badge variant="secondary" className="ml-1.5 text-[9px] px-1 py-0">
                          <Trans>Recommended</Trans>
                        </Badge>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  <Trans>~{estimatedActivities} activities, ~{estimatedMinutes} min</Trans>
                  {estimatedMinutes > 2 && <> <Trans>(Garmin rate limits apply)</Trans></>}
                </p>
                <Button onClick={handleSync} disabled={syncing}>
                  {syncing ? (
                    <span className="flex items-center gap-2">
                      <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                      <Trans>Syncing...</Trans>
                    </span>
                  ) : (
                    <Trans>Start sync</Trans>
                  )}
                </Button>
              </div>

              {syncKickoffError && (
                <Alert variant="destructive">
                  <AlertDescription>{syncKickoffError}</AlertDescription>
                </Alert>
              )}

              {/* Keep visible after sync ends so per-source errors survive `syncing` → false. */}
              {(syncing || syncDone) && Object.keys(liveSyncStatus).length > 0 && (
                <div className="space-y-1">
                  {Object.entries(liveSyncStatus).map(([src, status]) => (
                    <div key={src} className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground capitalize">{src}</span>
                      <span className={
                        status.status === 'syncing' ? 'text-primary' :
                        status.status === 'done' ? 'text-primary' :
                        status.status === 'error' ? 'text-destructive' :
                        'text-muted-foreground'
                      }>
                        {status.status === 'syncing' && (
                          <span className="flex items-center gap-1.5">
                            <span className="h-2.5 w-2.5 animate-spin rounded-full border border-primary border-t-transparent" />
                            {status.progress || 'Syncing...'}
                          </span>
                        )}
                        {status.status === 'done' && '✓ Done'}
                        {status.status === 'error' && `✗ ${status.error || 'Error'}`}
                        {status.status === 'idle' && '—'}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {syncDone && (() => {
                const failures = Object.entries(liveSyncStatus).filter(
                  ([, s]) => s.status === 'error',
                );
                const successes = Object.entries(liveSyncStatus).filter(
                  ([, s]) => s.status === 'done',
                );
                const total = failures.length + successes.length;
                if (failures.length > 0) {
                  return (
                    <Alert variant="destructive">
                      <AlertDescription className="text-sm">
                        <p className="font-medium">
                          <Plural
                            value={total}
                            one={<Trans>Sync failed for {failures.length} of # source.</Trans>}
                            other={<Trans>Sync failed for {failures.length} of # sources.</Trans>}
                          />
                        </p>
                        <ul className="mt-2 space-y-1 list-disc list-inside">
                          {failures.map(([src, s]) => (
                            <li key={src}>
                              <span className="capitalize">{src}</span>: {s.error || 'Unknown error'}
                            </li>
                          ))}
                        </ul>
                        <p className="mt-2 text-xs opacity-80">
                          <Trans>Check your credentials in the connection step, then try again.</Trans>
                        </p>
                      </AlertDescription>
                    </Alert>
                  );
                }
                return (
                  <Alert className="border-primary/30 bg-primary/5">
                    <AlertDescription className="text-sm text-primary">
                      <Trans>Sync complete! Your data is ready.</Trans>
                    </AlertDescription>
                  </Alert>
                );
              })()}
            </div>
          )}
          {setup.hasSyncedData && (
            <p className="mt-3 text-sm text-primary font-medium"><Trans>Data synced successfully</Trans></p>
          )}
        </SetupCard>

        {/* ===== STEP 3: Training Base ===== */}
        <SetupCard
          stepNum={3}
          title={t`Choose training base`}
          description={t`How your zones and training load are calculated`}
          done={setup.hasConnection}
          icon={<Gauge className="h-4 w-4" />}
          disabled={!setup.hasConnection}
        >
          <div className="grid grid-cols-3 gap-2 mt-4">
            {TRAINING_BASE_KEYS.map((base) => {
              const info = baseInfo(base);
              // Only highlight the active selection when user has connections
              const isActive = setup.hasConnection && config?.training_base === base;
              const isSuggested = suggestedBase === base && !isActive;
              return (
                <button
                  key={base}
                  onClick={() => handleBaseChange(base)}
                  className={`rounded-xl p-3 text-left transition-all border relative ${
                    isActive
                      ? 'border-primary/40 bg-primary/10'
                      : 'border-transparent bg-muted hover:bg-muted/80'
                  }`}
                >
                  <p className="font-semibold text-sm text-foreground">{info.label}</p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">{info.desc}</p>
                  {isSuggested && (
                    <div className="flex items-center gap-1 mt-2">
                      <Sparkles className="h-3 w-3 text-primary" />
                      <span className="text-[10px] text-primary font-medium"><Trans>Recommended</Trans></span>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </SetupCard>

        {/* ===== STEP 4: Goal ===== */}
        <SetupCard
          stepNum={4}
          title={t`Set a goal`}
          description={t`Target a race or track continuous improvement`}
          done={!!setup.steps.find((s) => s.key === 'goal')?.done}
          icon={<Target className="h-4 w-4" />}
        >
          <div className="mt-4">
            {config?.goal?.race_date || (config?.goal?.target_time_sec && Number(config.goal.target_time_sec) > 0) ? (
              <div className="flex items-center justify-between">
                <p className="text-sm text-primary font-medium">
                  {config.goal.race_date ? <Trans>Race goal configured</Trans> : <Trans>Continuous improvement configured</Trans>}
                </p>
                <Button variant="ghost" size="sm" onClick={() => setGoalEditorOpen(true)}>
                  <Trans>Edit</Trans>
                </Button>
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  <Trans>Optional — you can always set this later from the Goal page</Trans>
                </p>
                <Button variant="outline" size="sm" onClick={() => setGoalEditorOpen(true)}>
                  <Trans>Set goal</Trans>
                </Button>
              </div>
            )}
          </div>
        </SetupCard>

        {/* Skip / Continue */}
        <div className="flex justify-end pt-4">
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => navigate('/today')}
          >
            {setup.allDone ? <Trans>Go to dashboard</Trans> : <Trans>Skip for now</Trans>}
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Connect Platform Dialog */}
      <Dialog open={!!connectPlatform} onOpenChange={(open) => { if (!open) setConnectPlatform(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              <Trans>Connect {connectPlatform ? PLATFORM_META[connectPlatform]?.label : ''}</Trans>
            </DialogTitle>
            <DialogDescription>
              {connectPlatform && platformHelp(connectPlatform)}
            </DialogDescription>
          </DialogHeader>

          {/* Show what this platform provides */}
          {connectPlatform && (
            <div className="pb-2">
              <p className="text-xs text-muted-foreground mb-1.5"><Trans>Will sync:</Trans></p>
              <div className="flex flex-wrap gap-1.5">
                {PLATFORM_META[connectPlatform].categories.map((cat) => (
                  <Badge key={cat} variant="secondary" className="text-xs">
                    {platformCategoryLabel(cat)}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {connectError && (
            <Alert variant="destructive">
              <AlertDescription>{connectError}</AlertDescription>
            </Alert>
          )}

          {connectPlatform && connectPlatform !== 'strava' && (
            <form onSubmit={(e) => { e.preventDefault(); handleConnect(); }} className="space-y-4">
              {PLATFORM_META[connectPlatform].credFields.map((field) => (
                <div key={field.key} className="space-y-2">
                  <Label htmlFor={`setup-${field.key}`}>{credFieldLabel(field.key, field.label)}</Label>
                  <Input
                    id={`setup-${field.key}`}
                    type={field.type}
                    value={connectCreds[field.key] || ''}
                    onChange={(e) => setConnectCreds({ ...connectCreds, [field.key]: e.target.value })}
                    disabled={connecting}
                    autoComplete={field.key.includes('token') ? 'off' : field.type === 'password' ? 'current-password' : field.type}
                  />
                </div>
              ))}

              {/* Garmin region + activity types */}
              {connectPlatform === 'garmin' && (
                <div className="space-y-2">
                  <Label><Trans>Region</Trans></Label>
                  <div className="flex gap-2">
                    {([['international', 'International'], ['cn', 'China']] as const).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setGarminRegion(value)}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all border ${
                          garminRegion === value
                            ? 'border-primary/40 bg-primary/10 text-primary'
                            : 'border-border bg-muted text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {connectPlatform === 'garmin' && (
                <div className="space-y-2">
                  <Label><Trans>Activity types to sync</Trans></Label>
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => {
                        const allKeys = GARMIN_ACTIVITY_CATEGORIES.map((c) => c.key);
                        setSelectedCategories((prev) =>
                          prev.length === allKeys.length ? ['running'] : allKeys
                        );
                      }}
                      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-all border ${
                        selectedCategories.length === GARMIN_ACTIVITY_CATEGORIES.length
                          ? 'border-primary/40 bg-primary/10 text-primary'
                          : 'border-border bg-muted text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <Trans>All</Trans>
                    </button>
                    {GARMIN_ACTIVITY_CATEGORIES.map((cat) => {
                      const selected = selectedCategories.includes(cat.key);
                      return (
                        <button
                          key={cat.key}
                          type="button"
                          onClick={() => {
                            setSelectedCategories((prev) =>
                              selected
                                ? prev.filter((k) => k !== cat.key)
                                : [...prev, cat.key]
                            );
                          }}
                          className={`rounded-md px-2.5 py-1 text-xs font-medium transition-all border ${
                            selected
                              ? 'border-primary/40 bg-primary/10 text-primary'
                              : 'border-border bg-muted text-muted-foreground hover:text-foreground'
                          }`}
                        >
                          {activityCategoryLabel(cat.key)}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    <Trans>Cross-training activities affect your overall training load and recovery</Trans>
                  </p>
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setConnectPlatform(null)} disabled={connecting}>
                  <Trans>Cancel</Trans>
                </Button>
                <Button type="submit" disabled={connecting}>
                  {connecting ? <Trans>Connecting...</Trans> : <Trans>Connect</Trans>}
                </Button>
              </div>
            </form>
          )}

          {connectPlatform === 'strava' && (
            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-muted/40 p-3">
                <p className="text-sm font-medium text-foreground"><Trans>Activities-only connection</Trans></p>
                <p className="mt-1 text-xs text-muted-foreground">
                  <Trans>Continue in your browser to authorize Strava. Praxys imports activities from Strava, while recovery, fitness, and plans come from your other connected platforms.</Trans>
                </p>
              </div>

              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setConnectPlatform(null)} disabled={connecting}>
                  <Trans>Cancel</Trans>
                </Button>
                <Button type="button" onClick={() => void handleConnect()} disabled={connecting}>
                  {connecting ? <Trans>Redirecting...</Trans> : <Trans>Continue to Strava</Trans>}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Goal Editor */}
      <GoalEditor
        open={goalEditorOpen}
        onOpenChange={setGoalEditorOpen}
        initialType={config?.goal?.race_date ? 'race' : 'continuous'}
        initialRaceDate={config?.goal?.race_date as string || ''}
        initialDistance={config?.goal?.distance as string || 'marathon'}
        initialTargetTime={(config?.goal?.target_time_sec as number) || null}
        onSave={handleGoalSave}
      />

      {/* Primary Source Prompt — shown when connecting a second source for same category */}
      <Dialog open={!!primaryPrompt} onOpenChange={(open) => { if (!open) setPrimaryPrompt(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle><Trans>Choose primary source</Trans></DialogTitle>
            <DialogDescription>
              <Trans>
                Multiple platforms provide <strong>{primaryPrompt?.category}</strong> data.
                Which should be the primary source?
              </Trans>
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-wrap gap-2 py-2">
            {primaryPrompt?.options.map((platform) => (
              <Button
                key={platform}
                variant="outline"
                className="flex-1"
                onClick={async () => {
                  if (primaryPrompt) {
                    await updateSettings({
                      preferences: {
                        ...config?.preferences,
                        [primaryPrompt.category]: platform,
                      },
                    } as Partial<import('@/types/api').SettingsConfig>);
                    refetchSettings();
                  }
                  setPrimaryPrompt(null);
                }}
              >
                {PLATFORM_META[platform]?.label || platform}
              </Button>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// --- Step card wrapper ---

function SetupCard({
  stepNum,
  title,
  description,
  done,
  icon,
  disabled,
  children,
}: {
  stepNum: number;
  title: string;
  description: string;
  done: boolean;
  icon: React.ReactNode;
  disabled?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <Card className={`transition-opacity ${disabled ? 'opacity-50 pointer-events-none' : ''}`}>
      <CardContent className="pt-5 pb-4">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
              done
                ? 'bg-primary/15 text-primary'
                : 'bg-muted text-muted-foreground'
            }`}
          >
            {done ? <Check className="h-4 w-4" strokeWidth={3} /> : icon}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className={`text-sm font-semibold ${done ? 'text-muted-foreground' : 'text-foreground'}`}>
                {title}
              </h3>
              <span className="text-[10px] text-muted-foreground font-data">
                {stepNum}/4
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{description}</p>
          </div>
        </div>
        {children}
      </CardContent>
    </Card>
  );
}
