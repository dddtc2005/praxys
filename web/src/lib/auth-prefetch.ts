// Start the /api/auth/me fetch at module evaluation time — before React
// mounts or any useEffect runs. AuthProvider consumes this in-flight
// promise instead of creating a new one, shaving one React render cycle
// off the auth round-trip on every cold load.
import { KEYS, getCompatItem } from './storage-compat';

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

const token = (() => {
  try {
    return getCompatItem(KEYS.authToken.new, KEYS.authToken.legacy);
  } catch {
    return null;
  }
})();

export const prefetchedMeResponse: Promise<Response> | null = token
  ? fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
  : null;
