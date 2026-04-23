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

/**
 * Pull a human-readable error message out of a non-2xx fetch Response.
 *
 * Tolerates three shapes we actually see in practice:
 *  - FastAPI handler errors: `{detail: "..."}` or `{message: "..."}`
 *  - FastAPI 422 validation: `{detail: [{msg, loc, ...}, ...]}` — the array
 *    shape used to render as "[object Object]" when passed to React.
 *  - Non-JSON bodies (proxy HTML, empty) — falls back to `fallback`.
 */
async function extractErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (typeof data?.message === 'string') return data.message;
    if (Array.isArray(data?.detail) && data.detail.length > 0) {
      const first = data.detail[0];
      if (typeof first?.msg === 'string') return first.msg;
    }
  } catch { /* not JSON */ }
  return fallback;
}

export { API_BASE, getAuthHeaders, apiFetcher, extractErrorMessage };

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
