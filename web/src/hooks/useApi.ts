import { useQuery } from '@tanstack/react-query';
import { KEYS, getCompatItem, removeCompatItem } from '../lib/storage-compat';

const API_BASE = import.meta.env.VITE_API_URL || '';

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

function getAuthHeaders(): HeadersInit {
  const token = getCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
  if (token) {
    return { 'Authorization': `Bearer ${token}` };
  }
  return {};
}

async function apiFetcher<T>(url: string): Promise<T> {
  const fullUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const res = await fetch(fullUrl, {
    headers: getAuthHeaders(),
  });
  if (res.status === 401) {
    removeCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
    window.location.href = '/login';
    // Return a never-resolving promise to prevent React Query from
    // retrying or surfacing an error flash during the redirect.
    return new Promise<T>(() => {});
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export { API_BASE, getAuthHeaders, apiFetcher };

export function useApi<T>(url: string, options?: UseApiOptions): UseApiResult<T> {
  const { data, isLoading, error, refetch } = useQuery<T, Error>({
    queryKey: [url],
    queryFn: () => apiFetcher<T>(url),
    refetchInterval: options?.refetchInterval,
  });

  return {
    data: data ?? null,
    loading: isLoading,
    error: error?.message ?? null,
    refetch: () => { refetch(); },
  };
}
