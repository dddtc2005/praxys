import { useState, useEffect, useRef } from 'react';
import { useSettings } from '../contexts/SettingsContext';
import type { TrainingBase, SyncStatusResponse } from '../types/api';

const BASE_LABELS: Record<TrainingBase, { label: string; description: string }> = {
  power: { label: 'Power', description: 'Zone & load from Critical Power (Stryd / power meter)' },
  hr: { label: 'Heart Rate', description: 'Zone & load from Lactate Threshold HR' },
  pace: { label: 'Pace', description: 'Zone & load from Threshold Pace' },
};

const SOURCE_LABELS: Record<string, string> = {
  garmin: 'Garmin',
  stryd: 'Stryd',
  oura: 'Oura Ring',
};

const THRESHOLD_FIELDS = [
  { key: 'cp_watts', label: 'Critical Power', unit: 'W' },
  { key: 'lthr_bpm', label: 'LTHR', unit: 'bpm' },
  { key: 'threshold_pace_sec_km', label: 'Threshold Pace', unit: 'sec/km' },
  { key: 'max_hr_bpm', label: 'Max HR', unit: 'bpm' },
  { key: 'rest_hr_bpm', label: 'Resting HR', unit: 'bpm' },
];

export default function Settings() {
  const { config, display, availableProviders, availableBases, effectiveThresholds, loading, error, updateSettings, refetch } = useSettings();
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [editingThreshold, setEditingThreshold] = useState<string | null>(null);
  const [thresholdInput, setThresholdInput] = useState('');
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse>({});
  const [backfillDate, setBackfillDate] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll sync status when any source is syncing
  useEffect(() => {
    const anySyncing = Object.values(syncStatus).some((s) => s.status === 'syncing');
    if (anySyncing && !pollRef.current) {
      pollRef.current = setInterval(() => {
        fetch('/api/sync/status')
          .then((r) => r.json())
          .then((data: SyncStatusResponse) => {
            setSyncStatus(data);
            const stillSyncing = Object.values(data).some((s) => s.status === 'syncing');
            if (!stillSyncing) {
              if (pollRef.current) clearInterval(pollRef.current);
              pollRef.current = null;
              refetch(); // Reload settings after sync completes
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

  // Fetch initial sync status
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

  if (error || !config || !display) {
    return (
      <div className="rounded-2xl bg-panel p-6 text-center">
        <p className="text-accent-red font-semibold mb-2">Failed to load settings</p>
        <p className="text-sm text-text-muted">{error}</p>
      </div>
    );
  }

  const handleBaseChange = async (base: TrainingBase) => {
    setSaving(true);
    setSaveMsg('');
    try {
      await updateSettings({ training_base: base });
      setSaveMsg('Saved');
      setTimeout(() => setSaveMsg(''), 2000);
    } catch {
      setSaveMsg('Error saving');
    }
    setSaving(false);
  };

  const handleSourceChange = async (category: string, source: string) => {
    setSaving(true);
    setSaveMsg('');
    try {
      await updateSettings({ preferences: { ...config.preferences, [category]: source } });
      setSaveMsg('Saved');
      setTimeout(() => setSaveMsg(''), 2000);
    } catch {
      setSaveMsg('Error saving');
    }
    setSaving(false);
  };

  const handleThresholdSave = async (key: string) => {
    const val = parseFloat(thresholdInput);
    if (isNaN(val) || val <= 0) {
      setEditingThreshold(null);
      return;
    }
    setSaving(true);
    try {
      await updateSettings({ thresholds: { ...config.thresholds, [key]: val, source: 'manual' } });
      setSaveMsg('Saved');
      setTimeout(() => setSaveMsg(''), 2000);
    } catch {
      setSaveMsg('Error saving');
    }
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
      // Immediately poll status
      const res = await fetch('/api/sync/status');
      const data: SyncStatusResponse = await res.json();
      setSyncStatus(data);
    } catch {
      // ignore
    }
  };

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-text-primary">Settings</h1>
        <p className="text-sm text-text-secondary mt-1">Configure your training base, data sources, and thresholds</p>
        {saveMsg && (
          <p className={`text-xs mt-2 ${saveMsg === 'Saved' ? 'text-accent-green' : 'text-accent-red'}`}>
            {saveMsg}
          </p>
        )}
      </div>

      {/* Training Base */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6 mb-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-4">Training Base</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {availableBases.map((base) => {
            const info = BASE_LABELS[base];
            const isActive = config.training_base === base;
            return (
              <button
                key={base}
                onClick={() => handleBaseChange(base)}
                disabled={saving}
                className={`rounded-xl p-4 text-left transition-colors border-2 ${
                  isActive
                    ? 'border-accent-green bg-accent-green/10'
                    : 'border-border bg-panel-light hover:border-text-muted'
                }`}
              >
                <p className={`font-semibold ${isActive ? 'text-accent-green' : 'text-text-primary'}`}>
                  {info.label}
                </p>
                <p className="text-xs text-text-muted mt-1">{info.description}</p>
              </button>
            );
          })}
        </div>
      </div>

      {/* Data Sources + Sync */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">Data Sources</h2>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-xs text-text-muted whitespace-nowrap">Backfill from</label>
              <input
                type="date"
                value={backfillDate}
                onChange={(e) => setBackfillDate(e.target.value)}
                className="rounded-lg bg-panel-light border border-border px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-green"
              />
              {backfillDate && (
                <button
                  onClick={() => setBackfillDate('')}
                  className="text-xs text-text-muted hover:text-text-primary"
                  title="Clear backfill date"
                >
                  Clear
                </button>
              )}
            </div>
            <button
              onClick={() => handleSync()}
              disabled={Object.values(syncStatus).some((s) => s.status === 'syncing')}
              className="rounded-lg bg-accent-green/10 px-3 py-1.5 text-xs font-semibold text-accent-green hover:bg-accent-green/20 transition-colors disabled:opacity-50"
            >
              {backfillDate ? 'Backfill All' : 'Sync All'}
            </button>
          </div>
        </div>
        {backfillDate && (
          <p className="text-xs text-accent-yellow mb-4">
            Backfill mode: syncing from {backfillDate} to today. This may take longer than usual.
          </p>
        )}
        <div className="space-y-4">
          {Object.entries(availableProviders)
            .filter(([category]) => category !== 'fitness') // Fitness is auto-merged, no preference needed
            .map(([category, sources]) => {
            const sourceKey = config.preferences[category] || sources[0];
            const status = syncStatus[sourceKey];
            return (
              <div key={category} className="flex items-center justify-between">
                <div className="flex-1">
                  <p className="text-sm font-medium text-text-primary capitalize">{category}</p>
                  <p className="text-xs text-text-muted">
                    {category === 'activities' && 'Distance, pace, HR, power, splits'}
                    {category === 'recovery' && 'Sleep, HRV, readiness, resting HR'}
                    {category === 'plan' && 'Planned workouts and targets'}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {/* Sync status + button */}
                  <button
                    onClick={() => handleSync(sourceKey)}
                    disabled={status?.status === 'syncing'}
                    className="rounded-lg border border-border px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:border-text-muted transition-colors disabled:opacity-50"
                  >
                    {status?.status === 'syncing' ? (
                      <span className="flex items-center gap-1.5">
                        <span className="h-3 w-3 animate-spin rounded-full border border-accent-green border-t-transparent" />
                        Syncing
                      </span>
                    ) : status?.status === 'done' ? (
                      <span className="text-accent-green">Synced</span>
                    ) : status?.status === 'error' ? (
                      <span className="text-accent-red" title={status.error || ''}>Error</span>
                    ) : (
                      'Sync'
                    )}
                  </button>
                  <select
                    value={sourceKey}
                    onChange={(e) => handleSourceChange(category, e.target.value)}
                    disabled={saving}
                    className="rounded-lg bg-panel-light border border-border px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-green"
                  >
                    {sources.map((s) => (
                      <option key={s} value={s}>{SOURCE_LABELS[s] || s}</option>
                    ))}
                  </select>
                </div>
              </div>
            );
          })}
        </div>

        {/* Garmin region option */}
        {config.preferences.activities === 'garmin' && (
          <div className="mt-4 pt-4 border-t border-border flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-text-primary">Garmin Region</p>
              <p className="text-xs text-text-muted">Select China for Garmin CN accounts</p>
            </div>
            <select
              value={config.source_options?.garmin_region || 'international'}
              onChange={async (e) => {
                setSaving(true);
                try {
                  await updateSettings({ source_options: { ...config.source_options, garmin_region: e.target.value } });
                  setSaveMsg('Saved');
                  setTimeout(() => setSaveMsg(''), 2000);
                } catch { setSaveMsg('Error saving'); }
                setSaving(false);
              }}
              disabled={saving}
              className="rounded-lg bg-panel-light border border-border px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-green"
            >
              <option value="international">International</option>
              <option value="cn">China</option>
            </select>
          </div>
        )}
      </div>

      {/* Thresholds */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6 mb-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-4">Thresholds</h2>
        <p className="text-xs text-text-muted mb-4">
          Auto-detected from your data sources. Click a value to override manually.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          {THRESHOLD_FIELDS.map(({ key, label, unit }) => {
            const effective = effectiveThresholds[key];
            const value = effective?.value;
            const origin = effective?.origin ?? 'none';
            const isEditing = editingThreshold === key;

            return (
              <div key={key}>
                <label className="block text-xs text-text-muted mb-1">{label} ({unit})</label>
                {isEditing ? (
                  <div className="flex gap-1">
                    <input
                      type="number"
                      value={thresholdInput}
                      onChange={(e) => setThresholdInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleThresholdSave(key);
                        if (e.key === 'Escape') setEditingThreshold(null);
                      }}
                      autoFocus
                      className="w-full rounded-lg bg-panel-light border border-accent-green px-2 py-1 text-lg font-bold font-data text-text-primary focus:outline-none"
                    />
                    <button
                      onClick={() => handleThresholdSave(key)}
                      className="rounded-lg bg-accent-green/20 px-2 text-xs font-semibold text-accent-green"
                    >
                      Save
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => {
                      setEditingThreshold(key);
                      setThresholdInput(value != null ? String(value) : '');
                    }}
                    className="w-full text-left group"
                  >
                    <p className="text-lg font-bold font-data text-text-primary group-hover:text-accent-green transition-colors">
                      {value != null ? value : '—'}
                    </p>
                    <p className="text-[10px] text-text-muted mt-0.5">
                      {origin === 'none' ? 'Click to set' : origin}
                    </p>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Active Display Config */}
      <div className="rounded-2xl bg-panel p-5 sm:p-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-4">Active Display Config</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div>
            <p className="text-xs text-text-muted">Threshold</p>
            <p className="font-medium text-text-primary">{display.threshold_label}</p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Load Metric</p>
            <p className="font-medium text-text-primary">{display.load_label}</p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Intensity</p>
            <p className="font-medium text-text-primary">{display.intensity_metric}</p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Zones</p>
            <p className="font-medium text-text-primary text-xs">{display.zone_names.join(', ')}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
