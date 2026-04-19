import { useCallback, useEffect, useRef, useState } from 'react';
import { apiGet, ApiError } from '@/lib/api-client';

/**
 * Match the shape of the web useApi hook so components port cleanly:
 *   const { data, loading, error, refetch } = useApi<T>('/api/today');
 *
 * We don't use React Query here to keep the bundle small — the mini
 * program's quota is 2MB per package and TanStack Query pulls a lot in.
 */
export interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

interface UseApiOptions {
  /** If true (default), fetch on mount. Set false to call refetch() manually. */
  immediate?: boolean;
}

export function useApi<T>(path: string, options: UseApiOptions = {}): UseApiResult<T> {
  const { immediate = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(immediate);
  const [error, setError] = useState<string | null>(null);
  // Track component mount so we don't setState after unmount.
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const fetcher = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiGet<T>(path);
      if (mounted.current) setData(result);
    } catch (e) {
      const err = e as Partial<ApiError>;
      const message = err?.detail ?? (e instanceof Error ? e.message : String(e));
      if (mounted.current) setError(message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (immediate) void fetcher();
  }, [fetcher, immediate]);

  return { data, loading, error, refetch: fetcher };
}
