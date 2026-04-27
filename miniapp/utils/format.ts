// Mirrors web/src/lib/format.ts. Pure functions, no platform deps.
// Kept here as a copy because mini programs can't import outside the
// project root cleanly. Update both files when the formatting changes.

/** Format seconds as H:MM:SS */
export function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

const KM_TO_MILE = 1.60934;

/**
 * Format pace from sec/km to human-readable M:SS /km or /mi.
 *
 * @param secPerKm Pace in seconds per kilometer (internal storage format)
 * @param unit "metric" for min/km, "imperial" for min/mile. Default: metric.
 * @returns Formatted pace string like "5:30 /km" or "8:51 /mi"
 */
export function formatPace(secPerKm: number, unit: 'metric' | 'imperial' = 'metric'): string {
  if (!secPerKm || secPerKm <= 0) return '—';
  const totalSec = unit === 'imperial' ? secPerKm * KM_TO_MILE : secPerKm;
  const m = Math.floor(totalSec / 60);
  const s = Math.round(totalSec % 60);
  const suffix = unit === 'imperial' ? '/mi' : '/km';
  return `${m}:${String(s).padStart(2, '0')} ${suffix}`;
}

/** Format distance in km or miles. */
export function formatDistance(km: number, unit: 'metric' | 'imperial' = 'metric'): string {
  if (unit === 'imperial') {
    return `${(km / KM_TO_MILE).toFixed(1)} mi`;
  }
  return `${km.toFixed(1)} km`;
}

/** Parse H:MM:SS or MM:SS or raw seconds to total seconds.
 * 3-part = H:MM:SS, 2-part = MM:SS, 1-part = raw seconds. */
export function parseTimeToSeconds(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(':').map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 1 && parts[0] > 0) return parts[0];
  return null;
}
