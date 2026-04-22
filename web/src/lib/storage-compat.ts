// Dual-read shim for localStorage keys renamed during the Trainsight → Praxys
// rebrand. Reads from the new key first; falls back to legacy and migrates
// on first read. Writes always go to the new key, and any legacy value is
// cleared so a subsequent read path returns immediately.
//
// Remove this module after 2026-07-19 (90-day deprecation window). By that
// point every returning user's browser should have been migrated on first
// load, so the legacy keys are safe to drop.

export const KEYS = {
  authToken: { new: 'praxys-auth-token', legacy: 'trainsight-auth-token' },
  authEmail: { new: 'praxys-auth-email', legacy: 'trainsight-auth-email' },
  authAdmin: { new: 'praxys-auth-admin', legacy: 'trainsight-auth-admin' },
  theme: { new: 'praxys-theme', legacy: 'trainsight-theme' },
  locale: { new: 'praxys-locale', legacy: 'trainsight-locale' },
} as const;

export function getCompatItem(newKey: string, legacyKey: string): string | null {
  try {
    const fresh = localStorage.getItem(newKey);
    if (fresh !== null) return fresh;
    const legacy = localStorage.getItem(legacyKey);
    if (legacy !== null) {
      localStorage.setItem(newKey, legacy);
      localStorage.removeItem(legacyKey);
      return legacy;
    }
  } catch {
    // localStorage unavailable (private browsing, disabled, etc.)
  }
  return null;
}

export function setCompatItem(newKey: string, legacyKey: string, value: string): void {
  try {
    localStorage.setItem(newKey, value);
    localStorage.removeItem(legacyKey);
  } catch {
    // localStorage unavailable
  }
}

export function removeCompatItem(newKey: string, legacyKey: string): void {
  try {
    localStorage.removeItem(newKey);
    localStorage.removeItem(legacyKey);
  } catch {
    // localStorage unavailable
  }
}
