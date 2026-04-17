import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import type { ScienceResponse, TsbZoneConfig, SciencePillar } from '../types/api';
import { API_BASE, getAuthHeaders } from '../hooks/useApi';

interface ScienceContextValue {
  /** Active TSB zones from the load theory + label set. */
  tsbZones: TsbZoneConfig[];
  /** Full science response (active theories, available, recommendations). */
  science: ScienceResponse | null;
  loading: boolean;
  /** Update theory selections and/or label preference. */
  updateScience: (update: { science?: Partial<Record<SciencePillar, string>>; zone_labels?: string }) => Promise<void>;
  refetch: () => void;
}

/** Fallback zones if API hasn't loaded yet. */
const DEFAULT_TSB_ZONES: TsbZoneConfig[] = [
  { min: 25, max: null, label: 'Detraining', color: '#64748b' },
  { min: 5, max: 25, label: 'Performance', color: '#00ff87' },
  { min: -10, max: 5, label: 'Optimal', color: '#3b82f6' },
  { min: -25, max: -10, label: 'Productive', color: '#22c55e' },
  { min: null, max: -25, label: 'Overreaching', color: '#ef4444' },
];

const ScienceContext = createContext<ScienceContextValue>({
  tsbZones: DEFAULT_TSB_ZONES,
  science: null,
  loading: true,
  updateScience: async () => {},
  refetch: () => {},
});

export function ScienceProvider({ children }: { children: ReactNode }) {
  const [science, setScience] = useState<ScienceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchScience = useCallback(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/science`, { headers: getAuthHeaders() })
      .then((r) => {
        if (r.status === 401) {
          window.location.href = '/login';
          throw new Error('Unauthorized');
        }
        return r.json();
      })
      .then((data: ScienceResponse) => {
        setScience(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchScience();
  }, [fetchScience]);

  const tsbZones: TsbZoneConfig[] =
    science?.active?.load?.tsb_zones ?? DEFAULT_TSB_ZONES;

  const updateScience = useCallback(
    async (update: { science?: Partial<Record<SciencePillar, string>>; zone_labels?: string }) => {
      const res = await fetch(`${API_BASE}/api/science`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(update),
      });
      if (res.status === 401) {
        window.location.href = '/login';
        return;
      }
      fetchScience();
    },
    [fetchScience],
  );

  return (
    <ScienceContext.Provider value={{ tsbZones, science, loading, updateScience, refetch: fetchScience }}>
      {children}
    </ScienceContext.Provider>
  );
}

export function useScience() {
  return useContext(ScienceContext);
}

/** Get zone label + color for a TSB value. Uses the active science context. */
export function useTsbZone(tsb: number): { label: string; color: string } {
  const { tsbZones } = useScience();
  return tsbZoneFromConfig(tsb, tsbZones);
}

/** Pure function: classify a TSB value against a zone config. */
export function tsbZoneFromConfig(
  tsb: number,
  zones: TsbZoneConfig[],
): { label: string; color: string } {
  for (const zone of zones) {
    const aboveMin = zone.min == null || tsb >= zone.min;
    const belowMax = zone.max == null || tsb < zone.max;
    if (aboveMin && belowMax) {
      return { label: zone.label, color: zone.color };
    }
  }
  return { label: 'Unknown', color: '#64748b' };
}
