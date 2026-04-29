import { useState, useEffect } from 'react';
import { useSettings } from '@/contexts/SettingsContext';
import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { SyncStatusResponse } from '@/types/api';

const SETUP_DONE_KEY = 'praxys-setup-done';

function getCachedSetupDone(): boolean {
  try { return localStorage.getItem(SETUP_DONE_KEY) === 'true'; } catch { return false; }
}

function setCachedSetupDone(): void {
  try { localStorage.setItem(SETUP_DONE_KEY, 'true'); } catch { /* localStorage unavailable */ }
}

function clearCachedSetupDone(): void {
  try { localStorage.removeItem(SETUP_DONE_KEY); } catch { /* localStorage unavailable */ }
}

export interface SetupStep {
  key: string;
  label: string;
  description: string;
  done: boolean;
}

export interface SetupStatus {
  loading: boolean;
  steps: SetupStep[];
  completed: number;
  total: number;
  allDone: boolean;
  /** At least one platform has stored credentials. */
  hasConnection: boolean;
  /** At least one successful sync has occurred. */
  hasSyncedData: boolean;
  /** Which platforms have real connections (credentials stored). */
  connectedPlatforms: string[];
  /** Current sync status per platform. */
  syncStatus: SyncStatusResponse;
  /** Refresh connections + sync status. */
  refetch: () => void;
}

/**
 * Derives onboarding setup status from SettingsContext + connections API.
 * Used by the Setup page, nav badge, and redirect logic.
 */
export function useSetupStatus(): SetupStatus {
  const { config, loading: settingsLoading } = useSettings();
  // Cached flag: if setup was fully complete on a prior load, skip the
  // blocking API calls so TodayOrSetup renders Today immediately.
  // fetchKey > 0 (manual refetch) always re-runs the blocking path.
  const [cachedDone] = useState(() => getCachedSetupDone());
  const [connectedPlatforms, setConnectedPlatforms] = useState<string[]>([]);
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse>({});
  const [connectionsLoading, setConnectionsLoading] = useState(true);
  const [fetchKey, setFetchKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const isBackgroundRefresh = cachedDone && fetchKey === 0;

    if (!isBackgroundRefresh) setConnectionsLoading(true);

    Promise.all([
      fetch(`${API_BASE}/api/settings/connections`, { headers: getAuthHeaders() })
        .then((r) => r.ok ? r.json() : { connections: {} }),
      fetch(`${API_BASE}/api/sync/status`, { headers: getAuthHeaders() })
        .then((r) => r.ok ? r.json() : {}),
    ])
      .then(([connData, syncData]) => {
        if (cancelled) return;
        // Real connections = platforms with stored credentials
        const platforms = Object.keys(connData.connections || {});
        setConnectedPlatforms(platforms);
        setSyncStatus(syncData);
        if (!isBackgroundRefresh) setConnectionsLoading(false);
      })
      .catch(() => {
        if (!cancelled && !isBackgroundRefresh) setConnectionsLoading(false);
      });

    return () => { cancelled = true; };
  // cachedDone is stable (useState with no setter), so this never
  // causes extra runs — it's listed to satisfy the exhaustive-deps rule.
  }, [fetchKey, cachedDone]);

  // When the cache says setup was complete and this is the initial load,
  // skip the blocking wait so TodayOrSetup renders Today immediately.
  const loading = (cachedDone && fetchKey === 0) ? false : (settingsLoading || connectionsLoading);

  // Derive step completion
  const hasConnection = connectedPlatforms.length > 0;

  const hasSyncedData = Object.values(syncStatus).some(
    (s) => s.last_sync != null || s.status === 'done'
  );

  const goalConfigured = config?.goal
    ? (config.goal.race_date && config.goal.race_date !== '') ||
      (config.goal.target_time_sec && Number(config.goal.target_time_sec) > 0)
    : false;

  const steps: SetupStep[] = [
    {
      key: 'connect',
      label: 'Connect a platform',
      description: hasConnection
        ? `Connected: ${connectedPlatforms.join(', ')}`
        : 'Link Garmin, Strava, Stryd, or Oura to pull your training data',
      done: hasConnection,
    },
    {
      key: 'sync',
      label: 'Sync your data',
      description: hasSyncedData
        ? 'Data synced successfully'
        : 'Pull your latest activities, power data, and recovery metrics',
      done: hasSyncedData,
    },
    {
      key: 'base',
      label: 'Choose training base',
      description: hasConnection
        ? `Set to ${config?.training_base || 'power'}-based training`
        : 'Connect a platform first to choose your training base',
      // Done when user has a connection (making the choice meaningful)
      // and has explicitly selected a base (tracked by having a config row)
      done: hasConnection,
    },
    {
      key: 'goal',
      label: 'Set a goal',
      description: goalConfigured
        ? 'Goal configured'
        : 'Target a race or track continuous improvement',
      done: !!goalConfigured,
    },
  ];

  const completed = steps.filter((s) => s.done).length;
  const isActuallyDone = completed === steps.length;

  // Persist completion so the next cold load skips the blocking cascade.
  useEffect(() => {
    if (isActuallyDone) setCachedSetupDone();
  }, [isActuallyDone]);

  return {
    loading,
    steps,
    completed,
    total: steps.length,
    allDone: (cachedDone && fetchKey === 0) || isActuallyDone,
    hasConnection,
    hasSyncedData,
    connectedPlatforms,
    syncStatus,
    // Clear cache on manual refetch (e.g. after disconnecting a platform)
    // so the next render re-checks live state instead of using stale cache.
    refetch: () => { clearCachedSetupDone(); setFetchKey((k) => k + 1); },
  };
}
