import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSettings } from '@/contexts/SettingsContext';
import { useSetupStatus } from '@/hooks/useSetupStatus';
import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { TrainingBase, SyncStatusResponse } from '@/types/api';
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

// --- Platform metadata ---

/**
 * Official brand wordmark logos used in platform cards.
 * These replace text labels — the logo IS the name.
 */
function GarminWordmark({ className }: { className?: string }) {
  // Garmin wordmark — white PNG for dark theme, inverted for light
  return (
    <img
      src="/logos/garmin-white.png"
      alt="Garmin"
      className={`h-5 dark:invert-0 invert ${className ?? ''}`}
    />
  );
}

function StrydWordmark({ className }: { className?: string }) {
  // Stryd wordmark — orange-to-gold gradient
  return (
    <svg viewBox="0 0 427 109" fill="none" className={`h-5 w-auto ${className ?? ''}`} aria-label="Stryd">
      <path d="M0.659 88.881C4.509 95.84 15.317 108.869 39.451 108.869C63.437 108.869 74.245 96.136 78.243 88.881V62.082C74.541 55.716 67.138 48.313 44.485 43.427L37.674 41.946C31.308 40.614 28.939 38.689 27.606 36.172V28.028C29.235 25.215 33.084 21.958 39.451 21.958C45.669 21.958 49.815 24.919 51.296 28.028V35.876H78.243V20.625C74.541 13.815 63.437 0.785 39.451 0.785C15.317 0.785 4.361 13.815 0.659 20.625V46.092C4.212 52.458 11.912 59.565 34.713 64.599L41.376 66.08C47.446 67.412 49.815 69.337 51.296 72.002V81.626C49.519 84.736 45.669 87.697 39.451 87.697C33.084 87.697 29.235 84.736 27.606 81.626V73.039H0.659V88.881Z" fill="url(#stryd_g0)"/>
      <path d="M108.424 106.648H136.555V23.587H158.912V3.006H85.919V23.587H108.424V106.648Z" fill="url(#stryd_g1)"/>
      <path d="M169.875 106.648H198.006V70.226H205.113L226.286 106.648H248.643V91.546L232.504 66.524C239.019 63.415 244.053 58.529 247.458 52.458V20.625C240.944 9.373 229.247 3.006 215.921 3.006H169.875V106.648ZM198.006 50.83V23.587H209.555C214.885 23.587 219.031 25.659 220.807 29.213V45.351C219.031 48.905 215.181 50.83 209.555 50.83H198.006Z" fill="url(#stryd_g2)"/>
      <path d="M280.697 106.648H308.828V67.264L335.479 18.108V3.006H312.53L298.02 35.728H295.207L280.993 3.006H255.526V18.108L280.697 64.451V106.648Z" fill="url(#stryd_g3)"/>
      <path d="M374.551 86.068V23.587H386.1C392.318 23.587 396.612 26.4 398.092 29.953V79.701C396.612 83.255 392.318 86.068 386.1 86.068H374.551ZM346.419 106.648H392.022C410.974 106.648 421.782 95.988 426.224 86.216V23.439C421.782 13.667 410.974 3.006 392.022 3.006H346.419V106.648Z" fill="url(#stryd_g4)"/>
      <defs>
        <linearGradient id="stryd_g0" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g1" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g2" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g3" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g4" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
      </defs>
    </svg>
  );
}

function OuraWordmark({ className }: { className?: string }) {
  // Oura wordmark — the official ŌURA mark with ring symbol
  return (
    <svg viewBox="0 0 993 311" fill="none" className={`h-5 w-auto ${className ?? ''}`} aria-label="Oura">
      <path d="M63.443 27.388H190.38V0H63.443zM643.464 174.105H554.68V83.082h88.783c31.634 0 52.89 18.292 52.89 45.513 0 27.221-21.256 45.51-52.89 45.51m29.409 21.29c30.456-8.686 50.136-34.907 50.136-66.8 0-41.397-31.967-69.212-79.547-69.212H528.035v244.66h26.646V198.174h90.3l57.501 105.867h28.83l-59.946-108.218zM389.668 308.653c65.348 0 110.987-45.903 110.987-111.63V59.384h-27.387v135.793c0 50.688-34.377 86.09-83.6 86.09-40.798 0-84.709-26.94-84.709-86.09V59.384h-27.382v137.64c0 65.726 46.093 111.628 112.093 111.628m478.192-217.35 57.757 126.333H809.735zm-12.848-31.916L743.16 304.044h28.606l27.662-62.713h136.493l27.67 62.713h28.603L880.342 59.383zm-728.077-4.611C56.944 54.775 0 111.719 0 181.712c0 69.996 56.944 126.94 126.937 126.94 69.996 0 126.94-56.944 126.94-126.94 0-69.993-56.944-126.937-126.94-126.937m0 226.49c-54.893 0-99.553-44.66-99.553-99.553 0-54.892 44.661-99.55 99.554-99.55 54.894 0 99.556 44.658 99.556 99.55 0 54.893-44.662 99.553-99.556 99.553" fill="currentColor" />
    </svg>
  );
}

/**
 * Garmin activity type categories. Each category maps to multiple Garmin
 * API activitytype values. Selecting "Running" syncs all running subtypes.
 */
const GARMIN_ACTIVITY_CATEGORIES = [
  {
    key: 'running',
    label: 'Running',
    default: true,
    types: ['running', 'trail_running', 'treadmill_running', 'track_running', 'ultra_running', 'indoor_running'],
  },
  {
    key: 'cycling',
    label: 'Cycling',
    default: false,
    types: ['cycling', 'mountain_biking', 'indoor_cycling'],
  },
  {
    key: 'swimming',
    label: 'Swimming',
    default: false,
    types: ['swimming', 'open_water_swimming', 'lap_swimming'],
  },
  {
    key: 'hiking',
    label: 'Hiking',
    default: false,
    types: ['hiking'],
  },
  {
    key: 'walking',
    label: 'Walking',
    default: false,
    types: ['walking'],
  },
  {
    key: 'strength',
    label: 'Strength',
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

const BASE_SUGGEST: Record<string, TrainingBase> = {
  stryd: 'power',
  garmin: 'hr',
  oura: 'hr',
};

const BASE_CONFIG: Record<TrainingBase, { label: string; desc: string }> = {
  power: { label: 'Power', desc: 'Zones & load from Critical Power (best with Stryd)' },
  hr: { label: 'Heart Rate', desc: 'Zones & load from Lactate Threshold HR' },
  pace: { label: 'Pace', desc: 'Zones & load from Threshold Pace' },
};

const BACKFILL_OPTIONS = [
  { label: '1 month', days: 30 },
  { label: '3 months', days: 90 },
  { label: '6 months', days: 180, recommended: true },
  { label: '1 year', days: 365 },
];

// --- Component ---

export default function Setup() {
  const navigate = useNavigate();
  const { config, updateSettings, refetch: refetchSettings } = useSettings();
  const setup = useSetupStatus();

  // Connection state
  const [connectPlatform, setConnectPlatform] = useState<string | null>(null);
  const [connectCreds, setConnectCreds] = useState<Record<string, string>>({});
  const [connectError, setConnectError] = useState('');
  const [connecting, setConnecting] = useState(false);
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
  const [backfillDays, setBackfillDays] = useState(180);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [liveSyncStatus, setLiveSyncStatus] = useState<SyncStatusResponse>({});

  // Goal state
  const [goalEditorOpen, setGoalEditorOpen] = useState(false);

  // Redirect when all done
  useEffect(() => {
    if (!setup.loading && setup.allDone) {
      navigate('/', { replace: true });
    }
  }, [setup.loading, setup.allDone, navigate]);

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

  const handleSync = async () => {
    const fromDate = new Date();
    fromDate.setDate(fromDate.getDate() - backfillDays);
    const from = fromDate.toISOString().slice(0, 10);

    setSyncing(true);
    setSyncDone(false);
    try {
      await fetch(`${API_BASE}/api/sync`, {
        method: 'POST',
        headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_date: from }),
      });
      // Polling takes over from here
    } catch {
      setSyncing(false);
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
        <h1 className="text-2xl font-bold text-foreground">Set up Trainsight</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {setup.completed === 0
            ? 'Complete these steps to unlock your training insights'
            : `${setup.completed} of ${setup.total} steps complete`}
        </p>

        {/* Progress bar */}
        <div className="h-1.5 w-full rounded-full bg-muted mt-4">
          <div
            className="h-1.5 rounded-full bg-primary transition-all duration-500 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      <div className="space-y-4">
        {/* ===== STEP 1: Connect ===== */}
        <SetupCard
          stepNum={1}
          title="Connect a platform"
          description="Link at least one data source to start"
          done={setup.hasConnection}
          icon={<Link2 className="h-4 w-4" />}
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4">
            {(['garmin', 'stryd', 'oura'] as const).map((platform) => {
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
                  <p className="text-[11px] text-muted-foreground mb-2">{meta.detail}</p>
                  <div className="flex flex-wrap gap-1">
                    {meta.categories.map((cat) => (
                      <span
                        key={cat}
                        className="text-[10px] text-muted-foreground bg-muted rounded px-1.5 py-0.5"
                      >
                        {cat}
                      </span>
                    ))}
                  </div>
                  {!isConnected && (
                    <p className="text-xs text-primary mt-3 font-medium">Connect</p>
                  )}
                </button>
              );
            })}
          </div>
        </SetupCard>

        {/* ===== STEP 2: Sync ===== */}
        <SetupCard
          stepNum={2}
          title="Sync your data"
          description={
            !setup.hasConnection
              ? 'Connect a platform first'
              : 'Choose how much historical data to pull'
          }
          done={setup.hasSyncedData}
          icon={<RefreshCw className="h-4 w-4" />}
          disabled={!setup.hasConnection}
        >
          {setup.hasConnection && !setup.hasSyncedData && (
            <div className="mt-4 space-y-4">
              {/* Backfill range */}
              <div>
                <Label className="text-xs text-muted-foreground mb-2 block">Sync history</Label>
                <div className="flex flex-wrap gap-2">
                  {BACKFILL_OPTIONS.map((opt) => (
                    <button
                      key={opt.days}
                      onClick={() => setBackfillDays(opt.days)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all border ${
                        backfillDays === opt.days
                          ? 'border-primary/40 bg-primary/10 text-primary'
                          : 'border-transparent bg-muted text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {opt.label}
                      {opt.recommended && (
                        <Badge variant="secondary" className="ml-1.5 text-[9px] px-1 py-0">
                          Recommended
                        </Badge>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  ~{estimatedActivities} activities, ~{estimatedMinutes} min
                  {estimatedMinutes > 2 && ' (Garmin rate limits apply)'}
                </p>
                <Button onClick={handleSync} disabled={syncing}>
                  {syncing ? (
                    <span className="flex items-center gap-2">
                      <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                      Syncing...
                    </span>
                  ) : (
                    'Start sync'
                  )}
                </Button>
              </div>

              {/* Live sync progress */}
              {syncing && Object.keys(liveSyncStatus).length > 0 && (
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

              {syncDone && (
                <Alert className="border-primary/30 bg-primary/5">
                  <AlertDescription className="text-sm text-primary">
                    Sync complete! Your data is ready.
                  </AlertDescription>
                </Alert>
              )}
            </div>
          )}
          {setup.hasSyncedData && (
            <p className="mt-3 text-sm text-primary font-medium">Data synced successfully</p>
          )}
        </SetupCard>

        {/* ===== STEP 3: Training Base ===== */}
        <SetupCard
          stepNum={3}
          title="Choose training base"
          description="How your zones and training load are calculated"
          done={setup.hasConnection}
          icon={<Gauge className="h-4 w-4" />}
          disabled={!setup.hasConnection}
        >
          <div className="grid grid-cols-3 gap-2 mt-4">
            {(['power', 'hr', 'pace'] as const).map((base) => {
              const info = BASE_CONFIG[base];
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
                      <span className="text-[10px] text-primary font-medium">Recommended</span>
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
          title="Set a goal"
          description="Target a race or track continuous improvement"
          done={!!setup.steps.find((s) => s.key === 'goal')?.done}
          icon={<Target className="h-4 w-4" />}
        >
          <div className="mt-4">
            {config?.goal?.race_date || (config?.goal?.target_time_sec && Number(config.goal.target_time_sec) > 0) ? (
              <div className="flex items-center justify-between">
                <p className="text-sm text-primary font-medium">
                  {config.goal.race_date ? 'Race goal' : 'Continuous improvement'} configured
                </p>
                <Button variant="ghost" size="sm" onClick={() => setGoalEditorOpen(true)}>
                  Edit
                </Button>
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  Optional — you can always set this later from the Goal page
                </p>
                <Button variant="outline" size="sm" onClick={() => setGoalEditorOpen(true)}>
                  Set goal
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
            onClick={() => navigate('/')}
          >
            {setup.allDone ? 'Go to dashboard' : 'Skip for now'}
            <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Connect Platform Dialog */}
      <Dialog open={!!connectPlatform} onOpenChange={(open) => { if (!open) setConnectPlatform(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              Connect {connectPlatform ? PLATFORM_META[connectPlatform]?.label : ''}
            </DialogTitle>
            <DialogDescription>
              {connectPlatform && PLATFORM_META[connectPlatform]?.help}
            </DialogDescription>
          </DialogHeader>

          {/* Show what this platform provides */}
          {connectPlatform && (
            <div className="pb-2">
              <p className="text-xs text-muted-foreground mb-1.5">Will sync:</p>
              <div className="flex flex-wrap gap-1.5">
                {PLATFORM_META[connectPlatform].categories.map((cat) => (
                  <Badge key={cat} variant="secondary" className="text-xs">
                    {cat}
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

          {connectPlatform && (
            <form onSubmit={(e) => { e.preventDefault(); handleConnect(); }} className="space-y-4">
              {PLATFORM_META[connectPlatform].credFields.map((field) => (
                <div key={field.key} className="space-y-2">
                  <Label htmlFor={`setup-${field.key}`}>{field.label}</Label>
                  <Input
                    id={`setup-${field.key}`}
                    type={field.type}
                    value={connectCreds[field.key] || ''}
                    onChange={(e) => setConnectCreds({ ...connectCreds, [field.key]: e.target.value })}
                    disabled={connecting}
                    autoComplete={field.type === 'password' ? 'current-password' : field.type}
                  />
                </div>
              ))}

              {/* Garmin region + activity types */}
              {connectPlatform === 'garmin' && (
                <div className="space-y-2">
                  <Label>Region</Label>
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
                  <Label>Activity types to sync</Label>
                  <div className="flex flex-wrap gap-1.5">
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
                          {cat.label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    Cross-training activities affect your overall training load and recovery
                  </p>
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setConnectPlatform(null)} disabled={connecting}>
                  Cancel
                </Button>
                <Button type="submit" disabled={connecting}>
                  {connecting ? 'Connecting...' : 'Connect'}
                </Button>
              </div>
            </form>
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
            <DialogTitle>Choose primary source</DialogTitle>
            <DialogDescription>
              Multiple platforms provide <strong>{primaryPrompt?.category}</strong> data.
              Which should be the primary source?
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
