import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import type {
  StravaOAuthResult,
  StravaOAuthStartRequest,
  StravaOAuthStartResponse,
} from '@/types/api';

const STRAVA_STATUS_PARAM = 'strava';
const STRAVA_MESSAGE_PARAM = 'strava_message';

export function getStravaOAuthResult(search: string): StravaOAuthResult | null {
  const params = new URLSearchParams(search);
  const status = params.get(STRAVA_STATUS_PARAM);

  if (status !== 'connected' && status !== 'error') {
    return null;
  }

  return {
    status,
    message: params.get(STRAVA_MESSAGE_PARAM),
  };
}

export function stripStravaOAuthParams(search: string): string {
  const params = new URLSearchParams(search);
  params.delete(STRAVA_STATUS_PARAM);
  params.delete(STRAVA_MESSAGE_PARAM);

  const next = params.toString();
  return next ? `?${next}` : '';
}

export function buildStravaReturnTo(pathname: string, search = '', hash = ''): string {
  return `${pathname}${stripStravaOAuthParams(search)}${hash}`;
}

export function getStravaOAuthMessage(result: StravaOAuthResult): string {
  if (result.status === 'connected') {
    return 'Strava connected. Activities can be synced now.';
  }

  if (result.message === 'access_denied') {
    return 'Strava authorization was cancelled.';
  }

  if (result.message === 'missing_code') {
    return 'Strava did not return an authorization code.';
  }

  if (result.message) {
    return `Strava connection failed: ${result.message}`;
  }

  return 'Strava connection failed.';
}

export async function startStravaOAuth(
  returnTo: string,
  clientCreds?: { client_id: string; client_secret: string },
): Promise<never> {
  const payload: StravaOAuthStartRequest = {
    web_origin: window.location.origin,
    return_to: returnTo,
    ...clientCreds,
  };

  const res = await fetch(`${API_BASE}/api/settings/connections/strava/start`, {
    method: 'POST',
    headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (res.status === 401) {
    window.location.href = '/login';
    return new Promise<never>(() => {});
  }

  const data = await res.json().catch(() => null) as StravaOAuthStartResponse | { detail?: string } | null;
  if (!res.ok || !data || typeof data !== 'object' || !('authorize_url' in data)) {
    const message = data && 'detail' in data && data.detail
      ? data.detail
      : `Failed to start Strava OAuth (HTTP ${res.status})`;
    throw new Error(message);
  }

  window.location.assign(data.authorize_url);
  return new Promise<never>(() => {});
}
