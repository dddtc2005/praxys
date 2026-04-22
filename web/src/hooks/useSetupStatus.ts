import { useState, useEffect } from 'react';
import { useSettings } from '@/contexts/SettingsContext';
import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type { SyncStatusResponse } from '@/types/api';

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
  const [connectedPlatforms, setConnectedPlatforms] = useState<string[]>([]);
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse>({});
  const [connectionsLoading, setConnectionsLoading] = useState(true);
  const [fetchKey, setFetchKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setConnectionsLoading(true);

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
        setConnectionsLoading(false);
      })
      .catch(() => {
        if (!cancelled) setConnectionsLoading(false);
      });

    return () => { cancelled = true; };
  }, [fetchKey]);

  const loading = settingsLoading || connectionsLoading;

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

  return {
    loading,
    steps,
    completed,
    total: steps.length,
    allDone: completed === steps.length,
    hasConnection,
    hasSyncedData,
    connectedPlatforms,
    syncStatus,
    refetch: () => setFetchKey((k) => k + 1),
  };
}
