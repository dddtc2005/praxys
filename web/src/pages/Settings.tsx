import type React from 'react';
import { useState, useEffect, useRef } from 'react';
import { useSettings } from '@/contexts/SettingsContext';
import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { TrainingBase, SyncStatusResponse } from '@/types/api';
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
import { Link2, Gauge, SlidersHorizontal, Target, Activity, User, Check } from 'lucide-react';
import GoalEditor from '@/components/GoalEditor';
import { formatTime, formatPace } from '@/lib/format';
import { useAuth } from '@/hooks/useAuth';

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

const CAPABILITY_LABELS: Record<string, string> = {
  activities: 'Activities',
  recovery: 'Recovery',
  fitness: 'Fitness',
  plan: 'Plan',
};

const PREFERENCE_CATEGORIES = [
  { key: 'activities', label: 'Activities', desc: 'Primary source for workout data' },
  { key: 'recovery', label: 'Recovery', desc: 'Sleep, HRV, readiness' },
  { key: 'plan', label: 'Plan', desc: 'Training plan & targets' },
];

const BASE_CONFIG: Record<TrainingBase, { label: string; desc: string; icon: React.ReactNode }> = {
  power: {
    label: 'Power',
    desc: 'Zones & load from Critical Power',
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path d="M11.3 1.05a.75.75 0 01.4.9l-2.1 7.05h4.65a.75.75 0 01.58 1.22l-7.5 9a.75.75 0 01-1.28-.72l2.1-7.05H3.5a.75.75 0 01-.58-1.22l7.5-9a.75.75 0 01.88-.18z" />
      </svg>
    ),
  },
  hr: {
    label: 'Heart Rate',
    desc: 'Zones & load from Lactate Threshold HR',
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path d="M9.653 16.915l-.005-.003-.019-.01a20.8 20.8 0 01-1.162-.682 22.16 22.16 0 01-2.582-1.9C4.045 12.733 2 10.352 2 7.5a4.5 4.5 0 018-2.828A4.5 4.5 0 0118 7.5c0 2.852-2.044 5.233-3.885 6.82a22.05 22.05 0 01-3.744 2.582l-.019.01-.005.003h-.002z" />
      </svg>
    ),
  },
  pace: {
    label: 'Pace',
    desc: 'Zones & load from Threshold Pace',
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
      </svg>
    ),
  },
};

const THRESHOLD_FIELDS = [
  { key: 'cp_watts', label: 'Critical Power', unit: 'W' },
  { key: 'lthr_bpm', label: 'LTHR', unit: 'bpm' },
  { key: 'threshold_pace_sec_km', label: 'Threshold Pace', unit: '/km', isPace: true },
  { key: 'max_hr_bpm', label: 'Max HR', unit: 'bpm' },
  { key: 'rest_hr_bpm', label: 'Resting HR', unit: 'bpm' },
];

const CONNECTABLE_PLATFORMS = ['garmin', 'stryd', 'oura'] as const;

const PLATFORM_CRED_FIELDS: Record<string, { fields: { key: string; label: string; type: string }[]; help: string }> = {
  garmin: {
    fields: [
      { key: 'email', label: 'Email', type: 'email' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
    help: 'Use your Garmin Connect credentials.',
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

const DISTANCE_LABELS: Record<string, string> = {
  '5k': '5K', '10k': '10K', half: 'Half Marathon', marathon: 'Marathon',
  '50k': '50K', '50mi': '50 Mile', '100k': '100K', '100mi': '100 Mile',
};

// --- Component ---

export default function Settings() {
  const {
    config, platformCapabilities, availableProviders, availableBases,
    effectiveThresholds, loading, error, updateSettings, refetch,
  } = useSettings();
  const { email: authEmail, isDemo } = useAuth();

  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [editingThreshold, setEditingThreshold] = useState<string | null>(null);
  const [thresholdInput, setThresholdInput] = useState('');
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse>({});
  const [backfillDate, setBackfillDate] = useState('');
  const [showBackfill, setShowBackfill] = useState(false);
  const [connectPlatform, setConnectPlatform] = useState<string | null>(null);
  const [connectCreds, setConnectCreds] = useState<Record<string, string>>({});
  const [connectError, setConnectError] = useState('');
  const [connecting, setConnecting] = useState(false);
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
          <p className="text-destructive font-semibold mb-2">Failed to load settings</p>
          <p className="text-sm text-muted-foreground mb-3">{error}</p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>Retry</Button>
        </CardContent>
      </Card>
    );
  }

  const flash = (msg: string) => {
    setSaveMsg(msg);
    setTimeout(() => setSaveMsg(''), 2000);
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

  const handleThresholdSave = async (key: string) => {
    const val = parseFloat(thresholdInput);
    if (isNaN(val) || val <= 0) { setEditingThreshold(null); return; }
    setSaving(true);
    try {
      await updateSettings({ thresholds: { ...config.thresholds, [key]: val, source: 'manual' } });
      flash('Saved');
    } catch { flash('Error'); }
    setSaving(false);
    setEditingThreshold(null);
    refetch();
  };

  const handleSync = async (source?: string) => {
    const url = source ? `${API_BASE}/api/sync/${source}` : `${API_BASE}/api/sync`;
    const body = backfillDate ? JSON.stringify({ from_date: backfillDate }) : undefined;
    const headers: Record<string, string> = { ...getAuthHeaders() as Record<string, string> };
    if (body) headers['Content-Type'] = 'application/json';
    try {
      await fetch(url, { method: 'POST', headers, body });
      const res = await fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() });
      setSyncStatus(await res.json());
    } catch { /* ignore */ }
  };

  const handleRegionChange = async (region: string) => {
    setSaving(true);
    try {
      await updateSettings({ source_options: { ...config.source_options, garmin_region: region } });
      flash('Saved');
    } catch { flash('Error'); }
    setSaving(false);
  };

  const handleConnect = async () => {
    if (!connectPlatform) return;
    setConnecting(true);
    setConnectError('');
    try {
      const res = await fetch(`${API_BASE}/api/settings/connections/${connectPlatform}`, {
        method: 'POST',
        headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
        body: JSON.stringify(connectCreds),
      });
      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        setConnectError(data.message || `Failed to connect (HTTP ${res.status})`);
      } else {
        setConnectPlatform(null);
        setConnectCreds({});
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

  const preferredFor = (platform: string): string[] => {
    return Object.entries(config.preferences)
      .filter(([, src]) => src === platform)
      .map(([cat]) => cat);
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {isDemo ? 'Viewing configuration (read-only demo)' : 'Configure your training system'}
        </p>
        {saveMsg && (
          <p className={`text-xs mt-2 font-medium ${saveMsg === 'Saved' ? 'text-primary' : 'text-destructive'}`}>
            {saveMsg}
          </p>
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
                <CardTitle className="text-sm font-semibold text-foreground">Profile</CardTitle>
                <CardDescription className="text-xs">Your identity in Trainsight</CardDescription>
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
                        placeholder="Your name"
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
                        {config.display_name || <span className="text-muted-foreground italic font-normal">Set your name</span>}
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
                <Label className="text-xs text-muted-foreground">Units</Label>
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
            </div>
          </CardContent>
        </Card>

      {/* ===== SECTION 1: Connected Platforms ===== */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <SectionHeader
            icon={<Link2 className="h-4 w-4" />}
            title="Connected Platforms"
            description="Link your training devices and services"
          />
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowBackfill(!showBackfill)}>
              {showBackfill ? 'Hide backfill' : 'Backfill...'}
            </Button>
            <Button size="sm" onClick={() => handleSync()} disabled={anySyncing}>
              Sync All
            </Button>
          </div>
        </div>

        {showBackfill && (
          <Card className="mb-4">
            <CardContent className="pt-4 flex items-center gap-3 flex-wrap">
              <label className="text-xs text-muted-foreground">Sync from:</label>
              <Input
                type="date"
                value={backfillDate}
                onChange={(e) => setBackfillDate(e.target.value)}
                className="w-auto text-xs"
              />
              {backfillDate && (
                <>
                  <Button variant="secondary" size="sm" onClick={() => handleSync()} disabled={anySyncing}>
                    Backfill All
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setBackfillDate('')}>
                    Clear
                  </Button>
                  <span className="text-xs text-accent-amber">Historical sync may take several minutes</span>
                </>
              )}
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
                              <span className="text-xs text-muted-foreground">Connected</span>
                            </>
                          ) : (
                            <span className="text-xs text-muted-foreground">Not connected</span>
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
                              <span className="text-xs">{status?.progress || 'Syncing'}</span>
                            </span>
                          ) : status?.status === 'done' ? (
                            <span className="text-primary">Synced</span>
                          ) : status?.status === 'error' ? (
                            <span className="text-destructive" title={status.error || ''}>Error</span>
                          ) : (
                            'Sync'
                          )}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => { setConnectPlatform(platform); setConnectCreds({}); setConnectError(''); }}
                      >
                        Connect
                      </Button>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(caps)
                      .filter(([, supported]) => supported)
                      .map(([cap]) => (
                        <Badge key={cap} variant="secondary" className="text-xs font-normal">
                          {CAPABILITY_LABELS[cap] || cap}
                        </Badge>
                      ))}
                  </div>

                  {isConnected && prefs.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {prefs.map((cat) => (
                        <Badge key={cat} className="text-xs">
                          Primary for {cat}
                        </Badge>
                      ))}
                    </div>
                  )}

                  {isConnected && status?.last_sync && (
                    <p className="text-xs text-muted-foreground">
                      Last synced {new Date(status.last_sync).toLocaleString()}
                    </p>
                  )}

                  {isConnected && platform === 'garmin' && (
                    <>
                      <Separator />
                      <div className="flex items-center justify-between">
                        <Label className="text-xs text-muted-foreground">Region</Label>
                        <Select
                          value={String(config.source_options?.garmin_region || 'international')}
                          onValueChange={(v) => { if (v) handleRegionChange(v); }}
                          disabled={saving}
                        >
                          <SelectTrigger className="w-32 h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="international">International</SelectItem>
                            <SelectItem value="cn">China</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
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
                        Disconnect
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
            <DialogTitle>Connect {connectPlatform ? (PLATFORM_META[connectPlatform]?.label || connectPlatform) : ''}</DialogTitle>
            <DialogDescription>
              {connectPlatform && PLATFORM_CRED_FIELDS[connectPlatform]?.help}
            </DialogDescription>
          </DialogHeader>
          {connectError && (
            <Alert variant="destructive">
              <AlertDescription>{connectError}</AlertDescription>
            </Alert>
          )}
          {connectPlatform && PLATFORM_CRED_FIELDS[connectPlatform] && (
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
                    autoComplete={field.type === 'password' ? 'current-password' : field.type}
                  />
                </div>
              ))}
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

      {/* ===== SECTION 2: Training Base ===== */}
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Gauge className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">Training Base</CardTitle>
              <CardDescription className="text-xs">How your zones and training load are calculated</CardDescription>
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
                    <p className="font-semibold text-base text-foreground">{info.label}</p>
                  </div>
                  <p className={`text-xs ${isActive ? 'text-foreground/70' : 'text-muted-foreground'}`}>{info.desc}</p>
                </button>
              );
            })}
          </div>
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
              <CardTitle className="text-sm font-semibold text-foreground">Data Preferences</CardTitle>
              <CardDescription className="text-xs">Choose which platform to use for each data type</CardDescription>
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
                  <p className="text-sm font-medium text-foreground">{label}</p>
                  <p className="text-xs text-muted-foreground">{desc}</p>
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
              <p className="text-sm font-medium text-foreground">Fitness</p>
              <p className="text-xs text-muted-foreground">VO2max, CP, LTHR, training status</p>
            </div>
            <Badge variant="secondary">Auto-merged</Badge>
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
                <CardTitle className="text-sm font-semibold text-foreground">Goal</CardTitle>
                <CardDescription className="text-xs">Target a race or track continuous improvement</CardDescription>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => setGoalEditorOpen(true)}>
              {config.goal?.race_date || config.goal?.target_time_sec ? 'Edit' : 'Set goal'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {config.goal?.race_date || config.goal?.target_time_sec ? (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <div>
                <p className="text-xs text-muted-foreground">Mode</p>
                <p className="text-sm font-medium text-foreground">
                  {config.goal.race_date ? 'Race Goal' : 'Continuous Improvement'}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Distance</p>
                <p className="text-sm font-medium text-foreground">
                  {DISTANCE_LABELS[config.goal.distance ?? ''] || config.goal.distance || 'Marathon'}
                </p>
              </div>
              {config.goal.race_date && (
                <div>
                  <p className="text-xs text-muted-foreground">Race Date</p>
                  <p className="text-sm font-medium font-data text-foreground">{config.goal.race_date}</p>
                </div>
              )}
              {Number(config.goal.target_time_sec) > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground">Target Time</p>
                  <p className="text-sm font-medium font-data text-foreground">
                    {formatTime(Number(config.goal.target_time_sec))}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No goal set. Set a race target or distance goal to unlock predictions and countdown.
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

      {/* ===== SECTION 5: Thresholds ===== */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">Thresholds</CardTitle>
              <CardDescription className="text-xs">Drive your zone calculations and training load. Click to override.</CardDescription>
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
              const isEditing = editingThreshold === key;

              let badgeVariant: 'default' | 'secondary' | 'outline' = 'secondary';
              let badgeText = 'Not set';
              if (origin.startsWith('auto')) {
                badgeVariant = 'default';
                badgeText = origin.replace('auto (', '').replace(')', '');
                badgeText = `Auto · ${badgeText.charAt(0).toUpperCase() + badgeText.slice(1)}`;
              } else if (origin === 'manual') {
                badgeVariant = 'outline';
                badgeText = 'Manual';
              }

              return (
                <div key={key} className="rounded-xl bg-muted p-3 flex flex-col">
                  <p className="text-xs text-muted-foreground mb-2">{label}</p>

                  {isEditing ? (
                    <div className="flex flex-col gap-1.5">
                      <Input
                        type="number"
                        value={thresholdInput}
                        onChange={(e) => setThresholdInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleThresholdSave(key);
                          if (e.key === 'Escape') setEditingThreshold(null);
                        }}
                        autoFocus
                        className="text-xl font-bold font-data"
                      />
                      <div className="flex gap-1">
                        <Button size="sm" className="flex-1" onClick={() => handleThresholdSave(key)}>
                          Save
                        </Button>
                        <Button variant="ghost" size="sm" className="flex-1" onClick={() => setEditingThreshold(null)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => {
                        setEditingThreshold(key);
                        setThresholdInput(value != null ? String(value) : '');
                      }}
                      className="text-left group flex-1 flex flex-col"
                    >
                      <p className="text-2xl font-bold font-data text-foreground group-hover:text-primary transition-colors">
                        {value != null ? (isPace ? displayValue : value) : '—'}
                        <span className="text-xs font-normal text-muted-foreground ml-1">{value != null && !isPace ? unit : ''}</span>
                      </p>
                      <Badge variant={badgeVariant} className="mt-auto self-start text-[10px]">
                        {badgeText}
                      </Badge>
                    </button>
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
