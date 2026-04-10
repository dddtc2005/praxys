import { useQuery } from '@tanstack/react-query';

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

interface UseApiOptions {
  /** Poll interval in ms (e.g. 3000 for sync status). 0 = disabled. */
  refetchInterval?: number;
}

async function apiFetcher<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function useApi<T>(url: string, options?: UseApiOptions): UseApiResult<T> {
  const { data, isLoading, error, refetch } = useQuery<T, Error>({
    queryKey: [url],
    queryFn: () => apiFetcher<T>(url),
    staleTime: 2 * 60 * 1000,      // 2 min — data considered fresh
    gcTime: 5 * 60 * 1000,          // 5 min — cache kept (matches backend TTL)
    retry: 2,                        // retry twice with exponential backoff
    refetchOnWindowFocus: true,      // refresh when user returns to tab
    refetchInterval: options?.refetchInterval,
  });

  return {
    data: data ?? null,
    loading: isLoading,
    error: error?.message ?? null,
    refetch: () => { refetch(); },
  };
}
