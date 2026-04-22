import { SUPPORTED_LOCALES, DEFAULT_LOCALE, type SupportedLocale } from '../i18n/init';

/**
 * Map a BCP-47 language tag (e.g. "zh-CN", "en-GB") to a supported app locale.
 * Falls back to DEFAULT_LOCALE for anything unknown.
 */
export function detectLocaleFromTag(tag: string | null | undefined): SupportedLocale {
  if (!tag) return DEFAULT_LOCALE;
  const prefix = tag.toLowerCase().split('-')[0];
  return (SUPPORTED_LOCALES as readonly string[]).includes(prefix)
    ? (prefix as SupportedLocale)
    : DEFAULT_LOCALE;
}

/** Detect the user's preferred locale from `navigator.language`. Safe on SSR/tests. */
export function detectBrowserLocale(): SupportedLocale {
  if (typeof navigator === 'undefined') return DEFAULT_LOCALE;
  return detectLocaleFromTag(navigator.language);
}
