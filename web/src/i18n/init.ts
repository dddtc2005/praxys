import { i18n } from '@lingui/core';

export const SUPPORTED_LOCALES = ['en', 'zh'] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: SupportedLocale = 'en';

export function isSupportedLocale(value: unknown): value is SupportedLocale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/**
 * Load the catalog for `locale` and activate it.
 * Catalogs are compiled from .po files by @lingui/vite-plugin on demand.
 * English serves as the fallback — missing keys render their source text.
 */
export async function activateLocale(locale: SupportedLocale): Promise<void> {
  const { messages } = await import(`../locales/${locale}/messages.po`);
  i18n.loadAndActivate({ locale, messages });
}

export { i18n };
