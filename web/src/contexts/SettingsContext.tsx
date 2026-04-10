import { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import type { DisplayConfig, SettingsConfig, SettingsResponse, TrainingBase, ThresholdValue } from '../types/api';

interface SettingsContextValue {
  config: SettingsConfig | null;
  display: DisplayConfig | null;
  platformCapabilities: Record<string, Record<string, boolean>>;
  availableProviders: Record<string, string[]>;
  availableBases: TrainingBase[];
  effectiveThresholds: Record<string, ThresholdValue>;
  loading: boolean;
  error: string | null;
  updateSettings: (update: Partial<SettingsConfig>) => Promise<void>;
  refetch: () => void;
}

const DEFAULT_DISPLAY: DisplayConfig = {
  threshold_label: 'Critical Power',
  threshold_abbrev: 'CP',
  threshold_unit: 'W',
  load_label: 'RSS',
  load_unit: '',
  intensity_metric: 'Power',
  zone_names: ['Recovery', 'Endurance', 'Tempo', 'Threshold', 'VO2max'],
  trend_label: 'CP Trend',
};

const SettingsContext = createContext<SettingsContextValue>({
  config: null,
  display: DEFAULT_DISPLAY,
  platformCapabilities: {},
  availableProviders: {},
  availableBases: ['power', 'hr', 'pace'],
  effectiveThresholds: {},
  loading: true,
  error: null,
  updateSettings: async () => {},
  refetch: () => {},
});

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<SettingsConfig | null>(null);
  const [display, setDisplay] = useState<DisplayConfig>(DEFAULT_DISPLAY);
  const [platformCapabilities, setPlatformCapabilities] = useState<Record<string, Record<string, boolean>>>({});
  const [availableProviders, setAvailableProviders] = useState<Record<string, string[]>>({});
  const [availableBases, setAvailableBases] = useState<TrainingBase[]>(['power', 'hr', 'pace']);
  const [effectiveThresholds, setEffectiveThresholds] = useState<Record<string, ThresholdValue>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetchKey, setFetchKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch('/api/settings')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<SettingsResponse>;
      })
      .then((data) => {
        if (cancelled) return;
        setConfig(data.config);
        setDisplay(data.display);
        setPlatformCapabilities(data.platform_capabilities ?? {});
        setAvailableProviders(data.available_providers ?? {});
        setAvailableBases(data.available_bases);
        setEffectiveThresholds(data.effective_thresholds ?? {});
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [fetchKey]);

  const updateSettings = async (update: Partial<SettingsConfig>) => {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    setConfig(data.config);
    setDisplay(data.display);
  };

  const refetch = () => setFetchKey((k) => k + 1);

  return (
    <SettingsContext.Provider
      value={{ config, display, platformCapabilities, availableProviders, availableBases, effectiveThresholds, loading, error, updateSettings, refetch }}
    >
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  return useContext(SettingsContext);
}
