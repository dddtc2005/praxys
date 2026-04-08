import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useSettings } from '../contexts/SettingsContext';
import { useScience } from '../contexts/ScienceContext';
import type { TrainingBase, SyncStatusResponse, SciencePillar } from '../types/api';

// --- Constants ---

const PLATFORM_META: Record<string, { label: string; color: string; icon: JSX.Element }> = {
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

const BASE_CONFIG: Record<TrainingBase, { label: string; desc: string; icon: JSX.Element }> = {
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
  { key: 'threshold_pace_sec_km', label: 'Threshold Pace', unit: 'sec/km' },
  { key: 'max_hr_bpm', label: 'Max HR', unit: 'bpm' },
  { key: 'rest_hr_bpm', label: 'Resting HR', unit: 'bpm' },
];

const PILLAR_META: Record<string, { label: string; desc: string }> = {
  load: { label: 'Load & Fitness', desc: 'How training stress becomes fitness and fatigue' },
  recovery: { label: 'Recovery', desc: 'How readiness is assessed from recovery signals' },
  prediction: { label: 'Race Prediction', desc: 'Model used to predict race times' },
  zones: { label: 'Training Zones', desc: 'How intensity zones are defined' },
};

function ScienceFrameworkSection({
  saving, flash, setSaving,
}: {
  saving: boolean;
  flash: (msg: string) => void;
  setSaving: (v: boolean) => void;
}) {
  const { science, updateScience } = useScience();
  const [expandedPillar, setExpandedPillar] = useState<string | null>(null);

  if (!science) return null;

  const handleTheoryChange = async (pillar: SciencePillar, theoryId: string) => {
    setSaving(true);
    try {
      await updateScience({ science: { [pillar]: theoryId } });
      flash('Saved');
    } catch { flash('Error'); }
    setSaving(false);
  };

  const handleLabelsChange = async (labelId: string) => {
    setSaving(true);
    try {
      await updateScience({ zone_labels: labelId });
      flash('Saved');
    } catch { flash('Error'); }
    setSaving(false);
  };

  const recs = science.recommendations ?? [];
  const getRecommendation = (pillar: string) => recs.find((r) => r.pillar === pillar);

  return (
    <div className="rounded-2xl bg-panel p-5 sm:p-6 mb-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Science Framework
        </h2>
        <Link to="/science" className="text-xs text-text-muted hover:text-accent-green transition-colors">
          Learn more &rarr;
        </Link>
      </div>
      <p className="text-sm text-text-muted mb-4">
        Choose the scientific theories that drive your training analysis
      </p>

      <div className="space-y-3">
        {(['load', 'recovery', 'prediction', 'zones'] as SciencePillar[]).map((pillar) => {
          const meta = PILLAR_META[pillar];
          const active = science.active[pillar];
          const available = science.available[pillar] ?? [];
          const rec = getRecommendation(pillar);
          const isExpanded = expandedPillar === pillar;

          return (
            <div key={pillar} className="rounded-xl bg-panel-light overflow-hidden">
              {/* Row: pillar info + selector */}
              <div className="flex items-center justify-between gap-4 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-text-primary">{meta.label}</p>
                    {rec && rec.recommended_id !== active?.id && (
                      <span
                        className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold bg-accent-amber/10 text-accent-amber cursor-help"
                        title={rec.reason}
                      >
                        Suggestion available
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-text-muted">{meta.desc}</p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <div className="flex rounded-lg border border-border overflow-hidden">
                    {available.map((theory) => {
                      const isSelected = active?.id === theory.id;
                      const isRecommended = rec?.recommended_id === theory.id;
                      return (
                        <button
                          key={theory.id}
                          onClick={() => handleTheoryChange(pillar, theory.id)}
                          disabled={saving}
                          className={`px-3 py-1.5 text-xs font-medium transition-colors relative ${
                            isSelected
                              ? 'bg-accent-green/15 text-accent-green'
                              : 'bg-panel text-text-muted hover:text-text-secondary'
                          }`}
                          title={theory.description}
                        >
                          {theory.name}
                          {isRecommended && !isSelected && (
                            <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-accent-amber" />
                          )}
                        </button>
                      );
                    })}
                  </div>

                  <button
                    onClick={() => setExpandedPillar(isExpanded ? null : pillar)}
                    className="text-text-muted hover:text-text-secondary transition-colors p-1"
                  >
                    <span className="text-xs">{isExpanded ? '\u25be' : '\u25b8'}</span>
                  </button>
                </div>
              </div>

              {/* Expanded: description, citations, recommendation */}
              {isExpanded && active && (
                <div className="border-t border-border px-4 py-3 space-y-2">
                  <p className="text-xs text-text-secondary leading-relaxed">{active.description}</p>

                  {rec && rec.recommended_id !== active.id && (
                    <div className="rounded-lg bg-accent-amber/5 border border-accent-amber/20 px-3 py-2">
                      <p className="text-xs text-accent-amber font-medium">
                        Suggestion: {available.find((t) => t.id === rec.recommended_id)?.name}
                      </p>
                      <p className="text-xs text-text-muted mt-0.5">{rec.reason}</p>
                    </div>
                  )}

                  {active.citations?.length > 0 && (
                    <div>
                      <p className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Sources</p>
                      <div className="space-y-0.5">
                        {active.citations.map((c: any, i: number) => (
                          <p key={i} className="text-[10px] text-text-muted">
                            {c.title}
                            {c.year && ` (${c.year})`}
                            {c.url && (
                              <>
                                {' '}
                                <a href={c.url} target="_blank" rel="noopener noreferrer" className="underline hover:text-text-secondary">
                                  Link
                                </a>
                              </>
                            )}
                          </p>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* Label preference */}
        <div className="flex items-center justify-between gap-4 pt-2 mt-2 border-t border-border">
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary">Zone Labels</p>
            <p className="text-xs text-text-muted">Cosmetic only — does not affect calculations</p>
          </div>
          <div className="flex rounded-lg border border-border overflow-hidden shrink-0">
            {(science.label_sets ?? []).map((ls) => {
              const isSelected = science.active_labels === ls.id;
              return (
                <button
                  key={ls.id}
                  onClick={() => handleLabelsChange(ls.id)}
                  disabled={saving}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    isSelected
                      ? 'bg-accent-green/15 text-accent-green'
                      : 'bg-panel text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {ls.name}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Component ---

export default function Settings() {
  const {
    config, platformCapabilities, availableProviders, availableBases,
    effectiveThresholds, loading, error, updateSettings, refetch,
  } = useSettings();

  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [editingThreshold, setEditingThreshold] = useState<string | null>(null);
  const [thresholdInput, setThresholdInput] = useState('');
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse>({});
  const [backfillDate, setBackfillDate] = useState('');
  const [showBackfill, setShowBackfill] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll sync status
  useEffect(() => {
    const anySyncing = Object.values(syncStatus).some((s) => s.status === 'syncing');
    if (anySyncing && !pollRef.current) {
      pollRef.current = setInterval(() => {
        fetch('/api/sync/status')
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
    fetch('/api/sync/status')
      .then((r) => r.json())
      .then((data: SyncStatusResponse) => setSyncStatus(data))
      .catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent-green border-t-transparent" />
      </div>
    );
  }

  if (error || !config) {
    return (
      <div className="rounded-2xl bg-panel p-6 text-center">
        <p className="text-accent-red font-semibold mb-2">Failed to load settings</p>
        <p className="text-sm text-text-muted">{error}</p>
      </div>
    );
  }

  // --- Handlers ---

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
    const url = source ? `/api/sync/${source}` : '/api/sync';
    const body = backfillDate ? JSON.stringify({ from_date: backfillDate }) : undefined;
    try {
      await fetch(url, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body,
      });
      const res = await fetch('/api/sync/status');
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

  // --- Derived ---

  const connections = config.connections || [];
  const anySyncing = Object.values(syncStatus).some((s) => s.status === 'syncing');

  // What categories is each platform preferred for?
  const preferredFor = (platform: string): string[] => {
    return Object.entries(config.preferences)
      .filter(([, src]) => src === platform)
      .map(([cat]) => cat);
  };

  // --- Render ---

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-text-primary">Settings</h1>
        <p className="text-sm text-text-secondary mt-1">Configure your training system</p>
        {saveMsg && (
          <p className={`text-xs mt-2 font-medium ${saveMsg === 'Saved' ? 'text-accent-green' : 'text-accent-red'}`}>
            {saveMsg}
          </p>
        )}
      </div>

      {/* ===== SECTION 1: Connected Platforms ===== */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">Connected Platforms</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowBackfill(!showBackfill)}
              className="text-xs text-text-muted hover:text-text-secondary transition-colors"
            >
              {showBackfill ? 'Hide backfill' : 'Backfill...'}
            </button>
            <button
              onClick={() => handleSync()}
              disabled={anySyncing}
              className="rounded-lg bg-accent-green/10 px-3 py-1.5 text-xs font-semibold text-accent-green hover:bg-accent-green/20 transition-colors disabled:opacity-50"
            >
              Sync All
            </button>
          </div>
        </div>

        {/* Backfill controls (collapsible) */}
        {showBackfill && (
          <div className="rounded-xl bg-panel border border-border p-3 mb-4 flex items-center gap-3 flex-wrap">
            <label className="text-xs text-text-muted">Sync from:</label>
            <input
              type="date"
              value={backfillDate}
              onChange={(e) => setBackfillDate(e.target.value)}
              className="rounded-lg bg-panel-light border border-border px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-green"
            />
            {backfillDate && (
              <>
                <button
                  onClick={() => handleSync()}
                  disabled={anySyncing}
                  className="rounded-lg bg-accent-amber/15 px-3 py-1.5 text-xs font-semibold text-accent-amber hover:bg-accent-amber/25 transition-colors disabled:opacity-50"
                >
                  Backfill All
                </button>
                <button onClick={() => setBackfillDate('')} className="text-xs text-text-muted hover:text-text-primary">
                  Clear
                </button>
                <span className="text-xs text-accent-amber">Historical sync may take several minutes</span>
              </>
            )}
          </div>
        )}

        {/* Platform cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {connections.map((platform) => {
            const meta = PLATFORM_META[platform] || { label: platform, color: '#64748b', icon: null };
            const caps = platformCapabilities[platform] || {};
            const status = syncStatus[platform];
            const prefs = preferredFor(platform);
            const isSyncing = status?.status === 'syncing';

            return (
              <div
                key={platform}
                className="rounded-xl bg-panel border border-border p-4 flex flex-col gap-3"
              >
                {/* Platform header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div
                      className="rounded-lg p-1.5"
                      style={{ color: meta.color, backgroundColor: `${meta.color}15` }}
                    >
                      {meta.icon}
                    </div>
                    <div>
                      <p className="text-base font-semibold text-text-primary">{meta.label}</p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="h-1.5 w-1.5 rounded-full bg-accent-green" />
                        <span className="text-xs text-text-muted">Connected</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => handleSync(platform)}
                    disabled={isSyncing}
                    className="rounded-lg border border-border px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:border-text-muted transition-colors disabled:opacity-50"
                  >
                    {isSyncing ? (
                      <span className="flex items-center gap-1.5">
                        <span className="h-3 w-3 animate-spin rounded-full border border-accent-green border-t-transparent" />
                      </span>
                    ) : status?.status === 'done' ? (
                      <span className="text-accent-green text-xs">Synced</span>
                    ) : status?.status === 'error' ? (
                      <span className="text-accent-red text-xs" title={status.error || ''}>Error</span>
                    ) : (
                      'Sync'
                    )}
                  </button>
                </div>

                {/* Capability tags */}
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(caps)
                    .filter(([, supported]) => supported)
                    .map(([cap]) => (
                      <span
                        key={cap}
                        className="rounded-md px-1.5 py-0.5 text-xs font-medium bg-panel-light text-text-muted"
                      >
                        {CAPABILITY_LABELS[cap] || cap}
                      </span>
                    ))}
                </div>

                {/* Preferred for badges */}
                {prefs.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {prefs.map((cat) => (
                      <span
                        key={cat}
                        className="rounded-md px-1.5 py-0.5 text-xs font-semibold bg-accent-green/10 text-accent-green"
                      >
                        Primary for {cat}
                      </span>
                    ))}
                  </div>
                )}

                {/* Last synced */}
                {status?.last_sync && (
                  <p className="text-xs text-text-muted">
                    Last synced {new Date(status.last_sync).toLocaleString()}
                  </p>
                )}

                {/* Garmin region (only for Garmin) */}
                {platform === 'garmin' && (
                  <div className="flex items-center justify-between pt-2 border-t border-border">
                    <span className="text-xs text-text-muted">Region</span>
                    <select
                      value={config.source_options?.garmin_region || 'international'}
                      onChange={(e) => handleRegionChange(e.target.value)}
                      disabled={saving}
                      className="rounded-md bg-panel-light border border-border px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-green"
                    >
                      <option value="international">International</option>
                      <option value="cn">China</option>
                    </select>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ===== SECTION 2: Training Base ===== */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6 mb-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-4">Training Base</h2>
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
                    ? 'border-accent-green/40 bg-accent-green/10 shadow-[0_0_12px_rgba(0,255,135,0.08)]'
                    : 'border-transparent bg-panel-light hover:bg-panel-light/80'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={isActive ? 'text-accent-green' : 'text-text-muted'}>{info.icon}</span>
                  <p className={`font-semibold text-base ${isActive ? 'text-text-primary' : 'text-text-primary'}`}>
                    {info.label}
                  </p>
                </div>
                <p className={`text-xs ${isActive ? 'text-text-secondary' : 'text-text-muted'}`}>{info.desc}</p>
              </button>
            );
          })}
        </div>
      </div>

      {/* ===== SECTION 2.5: Science Framework ===== */}
      <ScienceFrameworkSection saving={saving} flash={flash} setSaving={setSaving} />

      {/* ===== SECTION 3: Data Preferences ===== */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6 mb-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1">Data Preferences</h2>
        <p className="text-sm text-text-muted mb-4">Choose which platform to use for each data type</p>

        <div className="space-y-3">
          {PREFERENCE_CATEGORIES.map(({ key, label, desc }) => {
            const providers = (availableProviders[key] || []).filter(
              (p) => connections.includes(p) || (key === 'plan' && p === 'ai')
            );
            const current = config.preferences[key] || providers[0];

            return (
              <div key={key} className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">{label}</p>
                  <p className="text-xs text-text-muted">{desc}</p>
                </div>
                <div className="flex rounded-lg border border-border overflow-hidden shrink-0">
                  {providers.map((p) => {
                    const isSelected = current === p;
                    const meta = PLATFORM_META[p];
                    return (
                      <button
                        key={p}
                        onClick={() => handlePreferenceChange(key, p)}
                        disabled={saving}
                        className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                          isSelected
                            ? 'bg-accent-green/15 text-accent-green'
                            : 'bg-panel-light text-text-muted hover:text-text-secondary'
                        }`}
                      >
                        {meta?.label || p}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* Fitness — auto-merged, info only */}
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-text-primary">Fitness</p>
              <p className="text-xs text-text-muted">VO2max, CP, LTHR, training status</p>
            </div>
            <span className="rounded-lg bg-panel-light border border-border px-3 py-1.5 text-xs text-text-muted">
              Auto-merged
            </span>
          </div>
        </div>
      </div>

      {/* ===== SECTION 4: Thresholds ===== */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1">Thresholds</h2>
        <p className="text-xs text-text-muted mb-5">Drive your zone calculations and training load. Click to override.</p>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {THRESHOLD_FIELDS.map(({ key, label, unit }) => {
            const effective = effectiveThresholds[key];
            const value = effective?.value;
            const origin = effective?.origin ?? 'none';
            const isEditing = editingThreshold === key;

            // Origin badge styling
            let badgeClass = 'bg-panel-light text-text-muted';
            let badgeText = 'Not set';
            if (origin.startsWith('auto')) {
              badgeClass = 'bg-accent-green/10 text-accent-green';
              badgeText = origin.replace('auto (', '').replace(')', '');
              badgeText = `Auto · ${badgeText.charAt(0).toUpperCase() + badgeText.slice(1)}`;
            } else if (origin === 'manual') {
              badgeClass = 'bg-accent-blue/10 text-accent-blue';
              badgeText = 'Manual';
            }

            return (
              <div
                key={key}
                className="rounded-xl bg-panel-light p-3 flex flex-col"
              >
                <p className="text-xs text-text-muted mb-2">{label}</p>

                {isEditing ? (
                  <div className="flex flex-col gap-1.5">
                    <input
                      type="number"
                      value={thresholdInput}
                      onChange={(e) => setThresholdInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleThresholdSave(key);
                        if (e.key === 'Escape') setEditingThreshold(null);
                      }}
                      autoFocus
                      className="w-full rounded-lg bg-panel border border-accent-green px-2 py-1 text-xl font-bold font-data text-text-primary focus:outline-none"
                    />
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleThresholdSave(key)}
                        className="flex-1 rounded-md bg-accent-green/20 py-1 text-xs font-semibold text-accent-green"
                      >
                        Save
                      </button>
                      <button
                        onClick={() => setEditingThreshold(null)}
                        className="flex-1 rounded-md bg-panel py-1 text-xs text-text-muted"
                      >
                        Cancel
                      </button>
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
                    <p className="text-2xl font-bold font-data text-text-primary group-hover:text-accent-green transition-colors">
                      {value != null ? value : '—'}
                      <span className="text-xs font-normal text-text-muted ml-1">{value != null ? unit : ''}</span>
                    </p>
                    <span className={`mt-auto rounded-md px-1.5 py-0.5 text-xs font-medium self-start ${badgeClass}`}>
                      {badgeText}
                    </span>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
