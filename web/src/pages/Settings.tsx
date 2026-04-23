import type React from 'react';
import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useSettings } from '@/contexts/SettingsContext';
import { API_BASE, getAuthHeaders, extractErrorMessage } from '@/hooks/useApi';
import type { TrainingBase, SyncStatusResponse } from '@/types/api';
import {
  buildStravaReturnTo,
  getStravaOAuthMessage,
  getStravaOAuthResult,
  startStravaOAuth,
  stripStravaOAuthParams,
} from '@/lib/strava-oauth';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Link2, Gauge, SlidersHorizontal, Target, Activity, User, Check, Clock } from 'lucide-react';
import GoalEditor from '@/components/GoalEditor';
import { formatTime, formatPace } from '@/lib/format';
import { useAuth } from '@/hooks/useAuth';
import { useLocale } from '@/contexts/LocaleContext';
import { detectBrowserLocale } from '@/lib/locale-detect';
import { Trans, useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';

// --- Constants ---

const PLATFORM_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  garmin: {
    label: 'Garmin',
    color: '#00b4d8',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-6 h-6">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 3" />
        <path d="M8 3.5l1 1M16 3.5l-1 1" strokeLinecap="round" />
      </svg>
    ),
  },
  strava: {
    label: 'Strava',
    color: '#fc4c02',
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        className="w-5 h-5"
        aria-hidden="true"
      >
        <path d="M13.25 2 7.1 13.55h3.84l2.31-4.2 2.37 4.2h3.83L13.25 2Z" />
        <path d="m10.47 15.18-2.2 4.02h4.4l-2.2-4.02Z" />
      </svg>
    ),
  },
  stryd: {
    label: 'Stryd',
    color: '#ff6b35',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-6 h-6">
        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    ),
  },
  oura: {
    label: 'Oura Ring',
    color: '#a78bfa',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-6 h-6">
        <circle cx="12" cy="12" r="7" />
        <circle cx="12" cy="12" r="4" />
      </svg>
    ),
  },
  ai: {
    label: 'AI',
    color: '#f59e0b',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-6 h-6">
        <path d="M12 2a4 4 0 0 1 4 4c0 1.1-.9 2-2 2h-4c-1.1 0-2-.9-2-2a4 4 0 0 1 4-4z" />
        <path d="M9 8v4M15 8v4M7 12h10M9 16v3M15 16v3M12 12v4" strokeLinecap="round" />
      </svg>
    ),
  },
};

const CAPABILITY_LABELS: Record<string, MessageDescriptor> = {
  activities: msg`Activities`,
  recovery: msg`Recovery`,
  fitness: msg`Fitness`,
  plan: msg`Plan`,
};

const PREFERENCE_CATEGORIES: { key: string; label: MessageDescriptor; desc: MessageDescriptor }[] = [
  { key: 'activities', label: msg`Activities`, desc: msg`Primary source for workout data` },
  { key: 'recovery', label: msg`Recovery`, desc: msg`Sleep, HRV, readiness` },
  { key: 'plan', label: msg`Plan`, desc: msg`Training plan & targets` },
];

const BASE_CONFIG: Record<TrainingBase, { label: MessageDescriptor; desc: MessageDescriptor; icon: React.ReactNode }> = {
  power: {
    label: msg`Power`,
    desc: msg`Zones & load from Critical Power`,
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path d="M11.3 1.05a.75.75 0 01.4.9l-2.1 7.05h4.65a.75.75 0 01.58 1.22l-7.5 9a.75.75 0 01-1.28-.72l2.1-7.05H3.5a.75.75 0 01-.58-1.22l7.5-9a.75.75 0 01.88-.18z" />
      </svg>
    ),
  },
  hr: {
    label: msg`Heart Rate`,
    desc: msg`Zones & load from Lactate Threshold HR`,
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path d="M9.653 16.915l-.005-.003-.019-.01a20.8 20.8 0 01-1.162-.682 22.16 22.16 0 01-2.582-1.9C4.045 12.733 2 10.352 2 7.5a4.5 4.5 0 018-2.828A4.5 4.5 0 0118 7.5c0 2.852-2.044 5.233-3.885 6.82a22.05 22.05 0 01-3.744 2.582l-.019.01-.005.003h-.002z" />
      </svg>
    ),
  },
  pace: {
    label: msg`Pace`,
    desc: msg`Zones & load from Threshold Pace`,
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
      </svg>
    ),
  },
};

const THRESHOLD_FIELDS: { key: string; label: MessageDescriptor; unit: string; isPace?: boolean }[] = [
  { key: 'cp_watts', label: msg`Critical Power`, unit: 'W' },
  { key: 'lthr_bpm', label: msg`LTHR`, unit: 'bpm' },
  { key: 'threshold_pace_sec_km', label: msg`Threshold Pace`, unit: '/km', isPace: true },
  { key: 'max_hr_bpm', label: msg`Max HR`, unit: 'bpm' },
  { key: 'rest_hr_bpm', label: msg`Resting HR`, unit: 'bpm' },
];

/** Hook returning a ``source → label`` function for fitness-data source
 *  names. Connected platforms capitalise their brand name; the special
 *  ``activities`` source — computed in-app from your own power-vs-duration
 *  — gets a translated, descriptive label so the option reads as a
 *  distinct choice rather than a connected platform. Hook form is required
 *  so ``t\`…\``` receives the active Lingui translator. */
function useThresholdSourceLabel() {
  const { t } = useLingui();
  return (source: string): string => {
    if (source === 'activities') return t`From activities`;
    return source.charAt(0).toUpperCase() + source.slice(1);
  };
}

const CONNECTABLE_PLATFORMS = ['garmin', 'strava', 'stryd', 'oura'] as const;
const SYNC_INTERVAL_OPTIONS = [
  { hours: 6,  recommended: true },
  { hours: 12, recommended: false },
  { hours: 24, recommended: false },
] as const;
const DEFAULT_SYNC_INTERVAL_HOURS = 6;

const PLATFORM_CRED_FIELDS: Record<string, { fields: { key: string; label: string; type: string }[]; help: string }> = {
  garmin: {
    fields: [
      { key: 'email', label: 'Email', type: 'email' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
    help: 'Use your Garmin Connect credentials.',
  },
  strava: {
    fields: [],
    help: 'Authorize Praxys with Strava in your browser. Praxys only syncs activities from Strava.',
  },
  stryd: {
    fields: [
      { key: 'email', label: 'Email', type: 'email' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
    help: 'Use your Stryd account credentials (stryd.com).',
  },
  oura: {
    fields: [
      { key: 'token', label: 'Personal Access Token', type: 'password' },
    ],
    help: 'Generate a token at cloud.ouraring.com/personal-access-tokens.',
  },
};

// --- Section Header ---

function SectionHeader({ icon, title, description }: { icon: React.ReactNode; title: string; description?: string }) {
  return (
    <div className="flex items-center gap-2.5 mb-4">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        {icon}
      </div>
      <div>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
    </div>
  );
}

const DISTANCE_LABELS: Record<string, MessageDescriptor> = {
  '5k': msg`5K`,
  '10k': msg`10K`,
  half: msg`Half Marathon`,
  marathon: msg`Marathon`,
  '50k': msg`50K`,
  '50mi': msg`50 Mile`,
  '100k': msg`100K`,
  '100mi': msg`100 Mile`,
};

// --- Component ---

export default function Settings() {
  const location = useLocation();
  const navigate = useNavigate();
  const {
    config, platformCapabilities, availableProviders, availableBases,
    effectiveThresholds, detectedThresholds, loading, error, updateSettings, refetch,
  } = useSettings();
  const { email: authEmail, isDemo } = useAuth();
  const { setLocale } = useLocale();
  const { t, i18n } = useLingui();
  const thresholdSourceLabel = useThresholdSourceLabel();

  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse>({});
  const [backfillDate, setBackfillDate] = useState('');
  const [showBackfill, setShowBackfill] = useState(false);
  const [connectPlatform, setConnectPlatform] = useState<string | null>(null);
  const [connectCreds, setConnectCreds] = useState<Record<string, string>>({});
  const [connectError, setConnectError] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [stravaNotice, setStravaNotice] = useState('');
  // Garmin region is captured with the credentials because International and
  // CN are two independent account systems. Defaults to the current value so
  // the dialog comes up pre-filled when the user is re-entering credentials
  // without intending to switch regions.
  const [connectRegion, setConnectRegion] = useState<'international' | 'cn'>(
    String(config?.source_options?.garmin_region) === 'cn' ? 'cn' : 'international'
  );
  const [goalEditorOpen, setGoalEditorOpen] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameInput, setNameInput] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const anySyncing = Object.values(syncStatus).some((s) => s.status === 'syncing');
    if (anySyncing && !pollRef.current) {
      pollRef.current = setInterval(() => {
        fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() })
          .then((r) => r.json())
          .then((data: SyncStatusResponse) => {
            setSyncStatus(data);
            if (!Object.values(data).some((s) => s.status === 'syncing')) {
              if (pollRef.current) clearInterval(pollRef.current);
              pollRef.current = null;
              refetch();
            }
          })
          .catch(() => {});
      }, 2000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [syncStatus, refetch]);

  useEffect(() => {
    fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((data: SyncStatusResponse) => setSyncStatus(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const oauthResult = getStravaOAuthResult(location.search);
    if (!oauthResult) return;

    const cleanedLocation = `${location.pathname}${stripStravaOAuthParams(location.search)}${location.hash}`;
    navigate(cleanedLocation, { replace: true });

    if (oauthResult.status === 'connected') {
      setConnectPlatform(null);
      setConnectCreds({});
      setConnectError('');
      setStravaNotice(getStravaOAuthMessage(oauthResult));
      refetch();
      fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() })
        .then((r) => r.json())
        .then((data: SyncStatusResponse) => setSyncStatus(data))
        .catch(() => {});
      return;
    }

    setStravaNotice('');
    setConnectPlatform('strava');
    setConnectError(getStravaOAuthMessage(oauthResult));
  }, [location.hash, location.pathname, location.search, navigate, refetch]);

  if (loading) {
    return (
      <div className="space-y-6 py-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-4 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Skeleton className="h-40 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
        <Skeleton className="h-32 rounded-2xl" />
      </div>
    );
  }

  if (error || !config) {
    return (
      <Card className="text-center">
        <CardContent className="pt-6">
          <p className="text-destructive font-semibold mb-2"><Trans>Failed to load settings</Trans></p>
          <p className="text-sm text-muted-foreground mb-3">{error}</p>
          <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
        </CardContent>
      </Card>
    );
  }

  const flash = (msg: string, durationMs?: number) => {
    setSaveMsg(msg);
    // Errors carry the API's detail string and need longer to read than "Saved".
    const ttl = durationMs ?? (msg === 'Saved' ? 2000 : 5000);
    setTimeout(() => setSaveMsg(''), ttl);
  };

  const handleBaseChange = async (base: TrainingBase) => {
    setSaving(true);
    try {
      await updateSettings({ training_base: base });
      flash('Saved');
    } catch { flash('Error'); }
    setSaving(false);
  };

  const handlePreferenceChange = async (category: string, source: string) => {
    setSaving(true);
    try {
      await updateSettings({ preferences: { ...config.preferences, [category]: source } });
      flash('Saved');
    } catch { flash('Error'); }
    setSaving(false);
  };

  // Writes only to preferences.threshold_sources; never to config.thresholds.
  const handleThresholdSourceChange = async (
    metricType: string,
    source: string,
  ) => {
    setSaving(true);
    try {
      const current = config.preferences?.threshold_sources ?? {};
      await updateSettings({
        preferences: {
          ...config.preferences,
          threshold_sources: { ...current, [metricType]: source },
        },
      });
      flash('Saved');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'unknown';
      console.error('threshold source change failed', { metricType, source, err });
      flash(`Error saving ${metricType} source: ${msg}`);
    }
    setSaving(false);
    refetch();
  };

  const handleSync = async (source?: string) => {
    const url = source ? `${API_BASE}/api/sync/${source}` : `${API_BASE}/api/sync`;
    const body = backfillDate ? JSON.stringify({ from_date: backfillDate }) : undefined;
    const headers: Record<string, string> = { ...getAuthHeaders() as Record<string, string> };
    if (body) headers['Content-Type'] = 'application/json';
    try {
      const kickoff = await fetch(url, { method: 'POST', headers, body });
      if (!kickoff.ok) {
        flash(await extractErrorMessage(kickoff, `Failed to start sync (HTTP ${kickoff.status})`));
        return;
      }
      // Backend sync endpoints return HTTP 200 with {status: "error"|"already_syncing"}
      // for missing credentials or in-flight syncs. Without this check those just
      // silently no-op — the exact bug this PR class is fixing.
      const data = await kickoff.json().catch(() => null);
      if (data?.status === 'error' && typeof data?.message === 'string') {
        flash(data.message);
        return;
      }
      if (data?.status === 'already_syncing') {
        flash(`Sync already in progress${data.source ? ` for ${data.source}` : ''}.`);
        return;
      }
      if (!source && Array.isArray(data?.sources) && data.sources.length === 0) {
        flash('No connected sources to sync. Connect a platform first.');
        return;
      }
      const res = await fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() });
      setSyncStatus(await res.json());
    } catch (err) {
      flash(err instanceof Error && err.message ? err.message : 'Network error');
    }
  };

  const handleSyncIntervalChange = async (value: string | null) => {
    if (!value) return;
    const hours = parseInt(value, 10);
    if (Number.isNaN(hours)) return;
    if (!SYNC_INTERVAL_OPTIONS.some((opt) => opt.hours === hours)) return;
    setSaving(true);
    try {
      await updateSettings({
        source_options: {
          ...config.source_options,
          sync_interval_hours: hours,
        },
      });
      flash('Saved');
    } catch (err) {
      const msg = err instanceof Error && err.message ? err.message : 'Error';
      flash(msg);
    }
    setSaving(false);
  };

  const handleConnect = async () => {
    if (!connectPlatform) return;
    setConnecting(true);
    setConnectError('');
    setStravaNotice('');

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
      const body: Record<string, unknown> = { ...connectCreds };
      // Garmin has two independent account systems (International vs CN) that
      // sit behind different SSO endpoints. Capture the region with the
      // credentials so the sync client targets the right one and the Settings
      // read-only label stays accurate.
      if (connectPlatform === 'garmin') {
        body.is_cn = connectRegion === 'cn';
      }
      const res = await fetch(`${API_BASE}/api/settings/connections/${connectPlatform}`, {
        method: 'POST',
        headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        setConnectError(data.message || `Failed to connect (HTTP ${res.status})`);
      } else {
        // Mirror the region into source_options so _sync_garmin (which reads
        // source_options.garmin_region first) stays consistent with the
        // encrypted is_cn we just wrote. Otherwise a reconnect that changes
        // region would leave the two fields disagreeing.
        if (connectPlatform === 'garmin') {
          await updateSettings({
            source_options: {
              ...(config?.source_options || {}),
              garmin_region: connectRegion,
            },
          });
        }
        setConnectPlatform(null);
        setConnectCreds({});
        setConnectRegion('international');
        refetch();
        // Refresh sync status
        fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() })
          .then((r) => r.json())
          .then((d: SyncStatusResponse) => setSyncStatus(d))
          .catch(() => {});
      }
    } catch {
      setConnectError('Network error');
    }
    setConnecting(false);
  };

  const handleDisconnect = async (platform: string) => {
    try {
      await fetch(`${API_BASE}/api/settings/connections/${platform}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
      refetch();
    } catch { /* ignore */ }
  };

  const handleNameSave = async () => {
    const trimmed = nameInput.trim();
    setSaving(true);
    try {
      await updateSettings({ display_name: trimmed });
      flash('Saved');
    } catch { flash('Error'); }
    setSaving(false);
    setEditingName(false);
  };

  const handleGoalSave = async (goal: { race_date: string; distance: string; target_time_sec: number }) => {
    await updateSettings({ goal });
    flash('Saved');
  };

  const connections = config.connections || [];
  const anySyncing = Object.values(syncStatus).some((s) => s.status === 'syncing');
  const rawSyncInterval = String(
    (config.source_options as Record<string, unknown> | undefined)?.sync_interval_hours
      ?? DEFAULT_SYNC_INTERVAL_HOURS
  );
  const configuredSyncInterval = parseInt(rawSyncInterval, 10);
  const syncIntervalHours = SYNC_INTERVAL_OPTIONS.some((opt) => opt.hours === configuredSyncInterval)
    ? configuredSyncInterval
    : DEFAULT_SYNC_INTERVAL_HOURS;

  const lastSyncMs = Object.values(syncStatus)
    .map((s) => (s.last_sync ? new Date(s.last_sync).getTime() : 0))
    .reduce((a, b) => Math.max(a, b), 0);
  const nextSyncLabel = lastSyncMs
    ? new Date(lastSyncMs + syncIntervalHours * 3600_000).toLocaleString(undefined, {
        weekday: 'short', hour: 'numeric', minute: '2-digit',
      })
    : null;

  const preferredFor = (platform: string): string[] => {
    return Object.entries(config.preferences)
      .filter(([, src]) => src === platform)
      .map(([cat]) => cat);
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground"><Trans>Settings</Trans></h1>
        <p className="text-sm text-muted-foreground mt-1">
          {isDemo ? <Trans>Viewing configuration (read-only demo)</Trans> : <Trans>Configure your training system</Trans>}
        </p>
        {saveMsg && (
          <p className={`text-xs mt-2 font-medium ${saveMsg === 'Saved' ? 'text-primary' : 'text-destructive'}`}>
            {saveMsg}
          </p>
        )}
        {stravaNotice && (
          <Alert className="mt-4 border-primary/30 bg-primary/5">
            <AlertDescription className="text-sm text-primary">{stravaNotice}</AlertDescription>
          </Alert>
        )}
      </div>

      {/* Read-only overlay for demo accounts */}
      <div className={isDemo ? 'opacity-60 pointer-events-none select-none' : ''}>

      {/* ===== SECTION 0: Profile ===== */}
      <Card className="mb-8">
          <CardHeader>
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <User className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground"><Trans>Profile</Trans></CardTitle>
                <CardDescription className="text-xs"><Trans>Your identity in Praxys</Trans></CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col sm:flex-row gap-4 sm:gap-8">
              {/* Avatar + Name */}
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-lg font-semibold tracking-wide text-primary ring-1 ring-primary/20">
                  {(() => {
                    const name = config.display_name || authEmail || '';
                    const parts = name.trim().split(/[\s@]+/);
                    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
                    return name.slice(0, 2).toUpperCase() || '?';
                  })()}
                </div>
                <div className="min-w-0">
                  {editingName ? (
                    <div className="flex items-center gap-2">
                      <Input
                        value={nameInput}
                        onChange={(e) => setNameInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleNameSave();
                          if (e.key === 'Escape') setEditingName(false);
                        }}
                        placeholder={t`Your name`}
                        className="h-8 w-48 text-sm"
                        autoFocus
                      />
                      <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-primary" onClick={handleNameSave}>
                        <Check className="h-4 w-4" />
                      </Button>
                    </div>
                  ) : (
                    <button
                      onClick={() => { setNameInput(config.display_name || ''); setEditingName(true); }}
                      className="text-left group"
                    >
                      <p className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors">
                        {config.display_name || <span className="text-muted-foreground italic font-normal"><Trans>Set your name</Trans></span>}
                      </p>
                    </button>
                  )}
                  {authEmail && (
                    <p className="text-xs text-muted-foreground mt-0.5 truncate">{authEmail}</p>
                  )}
                </div>
              </div>

              {/* Unit system */}
              <div className="flex items-center gap-3 sm:ml-auto">
                <Label className="text-xs text-muted-foreground"><Trans>Units</Trans></Label>
                <ToggleGroup
                  value={[config.unit_system || 'metric']}
                  onValueChange={(v) => {
                    if (v.length) updateSettings({ unit_system: v[v.length - 1] as 'metric' | 'imperial' });
                  }}
                >
                  <ToggleGroupItem value="metric" size="sm" disabled={saving}>km</ToggleGroupItem>
                  <ToggleGroupItem value="imperial" size="sm" disabled={saving}>mi</ToggleGroupItem>
                </ToggleGroup>
              </div>

              {/* Language */}
              <div className="flex items-center gap-3">
                <Label className="text-xs text-muted-foreground"><Trans>Language</Trans></Label>
                <Select
                  value={config.language ?? 'auto'}
                  onValueChange={async (v) => {
                    if (v === 'auto') {
                      await updateSettings({ language: null });
                      await setLocale(detectBrowserLocale());
                    } else if (v === 'en' || v === 'zh') {
                      await updateSettings({ language: v });
                      await setLocale(v);
                    }
                  }}
                >
                  <SelectTrigger className="w-32 h-8 text-xs" disabled={saving}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">{t`Auto`}</SelectItem>
                    <SelectItem value="en">English</SelectItem>
                    <SelectItem value="zh">中文</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

      {/* ===== SECTION 1: Connected Platforms ===== */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <SectionHeader
            icon={<Link2 className="h-4 w-4" />}
            title={t`Connected Platforms`}
            description={t`Link your training devices and services`}
          />
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowBackfill(!showBackfill)}>
              {showBackfill ? <Trans>Hide backfill</Trans> : <Trans>Backfill...</Trans>}
            </Button>
            <Button size="sm" onClick={() => handleSync()} disabled={anySyncing}>
              <Trans>Sync All</Trans>
            </Button>
          </div>
        </div>

        {showBackfill && (
          <Card className="mb-4">
            <CardContent className="pt-4 flex items-center gap-3 flex-wrap">
              <label className="text-xs text-muted-foreground"><Trans>Sync from:</Trans></label>
              <Input
                type="date"
                value={backfillDate}
                onChange={(e) => setBackfillDate(e.target.value)}
                className="w-auto text-xs"
              />
              {backfillDate && (
                <>
                  <Button variant="secondary" size="sm" onClick={() => handleSync()} disabled={anySyncing}>
                    <Trans>Backfill All</Trans>
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setBackfillDate('')}>
                    <Trans>Clear</Trans>
                  </Button>
                  <span className="text-xs text-accent-amber"><Trans>Historical sync may take several minutes</Trans></span>
                </>
              )}
            </CardContent>
          </Card>
        )}

        <Card className="mb-4">
          <CardContent className="pt-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-2.5">
              <Clock className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-foreground"><Trans>Auto sync frequency</Trans></p>
                <p className="text-xs text-muted-foreground">
                  <Trans>How often Praxys pulls new data in the background. Lower frequency uses less network and respects platform rate limits.</Trans>
                </p>
                {nextSyncLabel && (
                  <p className="text-xs text-muted-foreground mt-1.5">
                    <Trans>Next sync</Trans> <span className="font-data text-foreground">~{nextSyncLabel}</span>
                  </p>
                )}
              </div>
            </div>
            <Select
              value={String(syncIntervalHours)}
              onValueChange={handleSyncIntervalChange}
              disabled={saving}
            >
              <SelectTrigger className="w-full sm:w-auto sm:min-w-52 h-9 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SYNC_INTERVAL_OPTIONS.map((option) => (
                  <SelectItem key={option.hours} value={String(option.hours)}>
                    <span className="flex items-center gap-2">
                      <span>
                        <Trans>Every <span className="font-data">{option.hours}</span> hours</Trans>
                      </span>
                      {option.recommended && (
                        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          <Trans>recommended</Trans>
                        </span>
                      )}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          {CONNECTABLE_PLATFORMS.map((platform) => {
            const meta = PLATFORM_META[platform] || { label: platform, color: '#64748b', icon: null };
            const caps = platformCapabilities[platform] || {};
            const status = syncStatus[platform];
            const prefs = preferredFor(platform);
            const isSyncing = status?.status === 'syncing';
            const isConnected = connections.includes(platform);

            return (
              <Card key={platform} className={!isConnected ? 'opacity-70' : ''}>
                <CardContent className="pt-4 flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div
                        className="rounded-lg p-1.5"
                        style={{ color: meta.color, backgroundColor: `${meta.color}15` }}
                      >
                        {meta.icon}
                      </div>
                      <div>
                        <p className="text-base font-semibold text-foreground">{meta.label}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          {isConnected ? (
                            <>
                              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                              <span className="text-xs text-muted-foreground"><Trans>Connected</Trans></span>
                            </>
                          ) : (
                            <span className="text-xs text-muted-foreground"><Trans>Not connected</Trans></span>
                          )}
                        </div>
                      </div>
                    </div>
                    {isConnected ? (
                      <div className="flex items-center gap-1.5">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleSync(platform)}
                          disabled={isSyncing}
                        >
                          {isSyncing ? (
                            <span className="flex items-center gap-1.5">
                              <span className="h-3 w-3 animate-spin rounded-full border border-primary border-t-transparent" />
                              <span className="text-xs">{status?.progress || t`Syncing`}</span>
                            </span>
                          ) : status?.status === 'done' ? (
                            <span className="text-primary"><Trans>Synced</Trans></span>
                          ) : status?.status === 'error' ? (
                            <span className="text-destructive" title={status.error || ''}><Trans>Error</Trans></span>
                          ) : (
                            <Trans>Sync</Trans>
                          )}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => {
                          setConnectPlatform(platform);
                          setConnectCreds({});
                          setConnectError('');
                          setConnectRegion(
                            String(config?.source_options?.garmin_region) === 'cn' ? 'cn' : 'international'
                          );
                        }}
                      >
                        <Trans>Connect</Trans>
                      </Button>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(caps)
                      .filter(([, supported]) => supported)
                      .map(([cap]) => (
                        <Badge key={cap} variant="secondary" className="text-xs font-normal">
                          {CAPABILITY_LABELS[cap] ? i18n._(CAPABILITY_LABELS[cap]) : cap}
                        </Badge>
                      ))}
                  </div>

                  {isConnected && prefs.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {prefs.map((cat) => (
                        <Badge key={cat} className="text-xs">
                          <Trans>Primary for {CAPABILITY_LABELS[cat] ? i18n._(CAPABILITY_LABELS[cat]) : cat}</Trans>
                        </Badge>
                      ))}
                    </div>
                  )}

                  {isConnected && status?.last_sync && (
                    <p className="text-xs text-muted-foreground">
                      <Trans>Last synced {new Date(status.last_sync).toLocaleString()}</Trans>
                    </p>
                  )}

                  {isConnected && status?.status === 'error' && status.error && (
                    <p className="text-xs text-destructive break-words">
                      <Trans>Last sync failed: {status.error}</Trans>
                    </p>
                  )}

                  {isConnected && platform === 'garmin' && (
                    <>
                      <Separator />
                      <div className="flex items-center justify-between">
                        <Label className="text-xs text-muted-foreground"><Trans>Region</Trans></Label>
                        <span className="text-xs font-medium">
                          {String(config.source_options?.garmin_region) === 'cn'
                            ? <Trans>China</Trans>
                            : <Trans>International</Trans>}
                        </span>
                      </div>
                      <p className="text-[10px] text-muted-foreground -mt-1">
                        <Trans>Garmin International and Garmin China are separate accounts. To switch, disconnect and reconnect with the other account.</Trans>
                      </p>
                    </>
                  )}

                  {isConnected && (
                    <>
                      <Separator />
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs text-muted-foreground hover:text-destructive self-start"
                        onClick={() => handleDisconnect(platform)}
                      >
                        <Trans>Disconnect</Trans>
                      </Button>
                    </>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Connect Platform Dialog */}
      <Dialog open={!!connectPlatform} onOpenChange={(open) => { if (!open) setConnectPlatform(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle><Trans>Connect {connectPlatform ? (PLATFORM_META[connectPlatform]?.label || connectPlatform) : ''}</Trans></DialogTitle>
            <DialogDescription>
              {connectPlatform && PLATFORM_CRED_FIELDS[connectPlatform]?.help}
            </DialogDescription>
          </DialogHeader>
          {connectError && (
            <Alert variant="destructive">
              <AlertDescription>{connectError}</AlertDescription>
            </Alert>
          )}
          {connectPlatform && connectPlatform !== 'strava' && PLATFORM_CRED_FIELDS[connectPlatform] && (
            <form
              onSubmit={(e) => { e.preventDefault(); handleConnect(); }}
              className="space-y-4"
            >
              {PLATFORM_CRED_FIELDS[connectPlatform].fields.map((field) => (
                <div key={field.key} className="space-y-2">
                  <Label htmlFor={`connect-${field.key}`}>{field.label}</Label>
                  <Input
                    id={`connect-${field.key}`}
                    type={field.type}
                    value={connectCreds[field.key] || ''}
                    onChange={(e) => setConnectCreds({ ...connectCreds, [field.key]: e.target.value })}
                    disabled={connecting}
                    autoComplete={field.key.includes('token') ? 'off' : field.type === 'password' ? 'current-password' : field.type}
                  />
                </div>
              ))}
              {connectPlatform === 'garmin' && (
                <div className="space-y-2">
                  <Label><Trans>Region</Trans></Label>
                  <div className="flex gap-2">
                    {([['international', t`International`], ['cn', t`China`]] as const).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setConnectRegion(value)}
                        disabled={connecting}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all border ${
                          connectRegion === value
                            ? 'border-primary/40 bg-primary/10 text-primary'
                            : 'border-border bg-muted text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    <Trans>Garmin International and Garmin China are separate account systems. Pick the one your credentials belong to.</Trans>
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

      {/* ===== SECTION 2: Training Base ===== */}
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Gauge className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground"><Trans>Training Base</Trans></CardTitle>
              <CardDescription className="text-xs"><Trans>How your zones and training load are calculated</Trans></CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {availableBases.map((base) => {
              const info = BASE_CONFIG[base];
              const isActive = config.training_base === base;
              return (
                <button
                  key={base}
                  onClick={() => handleBaseChange(base)}
                  disabled={saving}
                  className={`rounded-xl p-4 text-left transition-all border ${
                    isActive
                      ? 'border-primary/40 bg-primary/10'
                      : 'border-transparent bg-muted hover:bg-muted/80'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={isActive ? 'text-primary' : 'text-muted-foreground'}>{info.icon}</span>
                    <p className="font-semibold text-base text-foreground">{i18n._(info.label)}</p>
                  </div>
                  <p className={`text-xs ${isActive ? 'text-foreground/70' : 'text-muted-foreground'}`}>{i18n._(info.desc)}</p>
                </button>
              );
            })}
          </div>
          {config.training_base === 'power' && !connections.includes('stryd') && (
            <div
              className="mt-4 rounded-lg border border-accent-cobalt/30 bg-accent-cobalt/5 p-3"
              style={{ borderLeftWidth: '3px', borderLeftColor: 'var(--color-accent-cobalt)' }}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--color-accent-cobalt)' }}>
                <Trans>Note on Garmin native power</Trans>
              </p>
              <p className="text-xs text-foreground">
                <Trans>
                  Garmin native running power reads ~30% higher than Stryd for
                  the same athlete — they measure different things. Zones and
                  benchmarks calibrated on Stryd (most coach references, most
                  training literature) will not directly transfer. Your power
                  data will still be internally consistent for tracking progress,
                  but don't compare CP values across the two systems.
                </Trans>
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ===== SECTION 3: Data Preferences ===== */}
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <SlidersHorizontal className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground"><Trans>Data Preferences</Trans></CardTitle>
              <CardDescription className="text-xs"><Trans>Choose which platform to use for each data type</Trans></CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {PREFERENCE_CATEGORIES.map(({ key, label, desc }) => {
            const providers = (availableProviders[key as keyof typeof availableProviders] || []).filter(
              (p: string) => (connections as string[]).includes(p) || (key === 'plan' && p === 'ai')
            );
            const current = (config.preferences as Record<string, string>)[key] || providers[0];

            return (
              <div key={key} className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{i18n._(label)}</p>
                  <p className="text-xs text-muted-foreground">{i18n._(desc)}</p>
                </div>
                <ToggleGroup
                  value={[current]}
                  onValueChange={(v) => { if (v.length) handlePreferenceChange(key, v[v.length - 1]); }}
                >
                  {providers.map((p) => {
                    const meta = PLATFORM_META[p];
                    return (
                      <ToggleGroupItem key={p} value={p} size="sm" disabled={saving}>
                        {meta?.label || p}
                      </ToggleGroupItem>
                    );
                  })}
                </ToggleGroup>
              </div>
            );
          })}

          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground"><Trans>Fitness</Trans></p>
              <p className="text-xs text-muted-foreground"><Trans>VO2max, CP, LTHR, training status</Trans></p>
            </div>
            <Badge variant="secondary"><Trans>Auto-merged</Trans></Badge>
          </div>
        </CardContent>
      </Card>

      {/* ===== SECTION 4: Goal ===== */}
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Target className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground"><Trans>Goal</Trans></CardTitle>
                <CardDescription className="text-xs"><Trans>Target a race or track continuous improvement</Trans></CardDescription>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => setGoalEditorOpen(true)}>
              {config.goal?.race_date || config.goal?.target_time_sec ? <Trans>Edit</Trans> : <Trans>Set goal</Trans>}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {config.goal?.race_date || config.goal?.target_time_sec ? (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <div>
                <p className="text-xs text-muted-foreground"><Trans>Mode</Trans></p>
                <p className="text-sm font-medium text-foreground">
                  {config.goal.race_date ? <Trans>Race Goal</Trans> : <Trans>Continuous Improvement</Trans>}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground"><Trans>Distance</Trans></p>
                <p className="text-sm font-medium text-foreground">
                  {DISTANCE_LABELS[config.goal.distance ?? ''] ? i18n._(DISTANCE_LABELS[config.goal.distance ?? '']) : (config.goal.distance || t`Marathon`)}
                </p>
              </div>
              {config.goal.race_date && (
                <div>
                  <p className="text-xs text-muted-foreground"><Trans>Race Date</Trans></p>
                  <p className="text-sm font-medium font-data text-foreground">{config.goal.race_date}</p>
                </div>
              )}
              {Number(config.goal.target_time_sec) > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground"><Trans>Target Time</Trans></p>
                  <p className="text-sm font-medium font-data text-foreground">
                    {formatTime(Number(config.goal.target_time_sec))}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              <Trans>No goal set. Set a race target or distance goal to unlock predictions and countdown.</Trans>
            </p>
          )}
        </CardContent>
      </Card>

      <GoalEditor
        open={goalEditorOpen}
        onOpenChange={setGoalEditorOpen}
        initialType={config.goal?.race_date ? 'race' : 'continuous'}
        initialRaceDate={String(config.goal?.race_date || '')}
        initialDistance={String(config.goal?.distance || 'marathon')}
        initialTargetTime={Number(config.goal?.target_time_sec) || null}
        onSave={handleGoalSave}
      />

      {/* ===== SECTION 5: Thresholds =====
           Read-only by design: every value comes from a connected source
           or a calculation on the user's own data. When a metric has more
           than one source (e.g. Stryd + Garmin for CP), the user picks
           which source to use — they never type a value. */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground"><Trans>Thresholds</Trans></CardTitle>
              <CardDescription className="text-xs">
                <Trans>Drive your zone calculations and training load. Values come from connected sources; pick which source to use when you have more than one.</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {THRESHOLD_FIELDS.map(({ key, label, unit, isPace }) => {
              const effective = effectiveThresholds[key];
              const value = effective?.value;
              const displayValue = isPace && value != null
                ? formatPace(value, config.unit_system as 'metric' | 'imperial' || 'metric')
                : value;
              const origin = effective?.origin ?? 'none';

              // Threshold key -> metric_type in fitness_data (used as the
              // key under preferences.threshold_sources).
              const metricType = ({
                cp_watts: 'cp_estimate',
                lthr_bpm: 'lthr_bpm',
                threshold_pace_sec_km: 'lt_pace_sec_km',
                max_hr_bpm: 'max_hr_bpm',
                rest_hr_bpm: 'rest_hr_bpm',
              } as Record<string, string>)[key] || key;

              const detected = detectedThresholds[key];
              const options = detected?.options ?? [];
              const currentSource = origin.startsWith('auto')
                ? origin.replace('auto (', '').replace(')', '')
                : null;

              const badgeText = origin.startsWith('auto') && currentSource
                ? thresholdSourceLabel(currentSource)
                : t`Not set`;
              const badgeVariant: 'default' | 'secondary' = origin.startsWith('auto') ? 'default' : 'secondary';

              return (
                <div key={key} className="rounded-xl bg-muted p-3 flex flex-col">
                  <p className="text-xs text-muted-foreground mb-2">{i18n._(label)}</p>
                  <p className="text-2xl font-bold font-data text-foreground">
                    {value != null ? (isPace ? displayValue : value) : '\u2014'}
                    <span className="text-xs font-normal text-muted-foreground ml-1">
                      {value != null && !isPace ? unit : ''}
                    </span>
                  </p>
                  {options.length > 1 ? (
                    <Select
                      value={currentSource ?? options[0].source}
                      onValueChange={(v) => v && handleThresholdSourceChange(metricType, v)}
                      disabled={saving}
                    >
                      <SelectTrigger className="h-7 text-[11px] mt-auto">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {options.map((opt) => (
                          <SelectItem key={opt.source} value={opt.source} className="text-xs">
                            {thresholdSourceLabel(opt.source)}
                            <span className="text-muted-foreground ml-1 font-data">
                              ({isPace
                                ? formatPace(opt.value, config.unit_system as 'metric' | 'imperial' || 'metric')
                                : `${opt.value} ${unit}`})
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Badge variant={badgeVariant} className="mt-auto self-start text-[10px]">
                      {badgeText}
                    </Badge>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      </div>{/* end read-only overlay */}
    </div>
  );
}
