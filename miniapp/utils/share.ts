/**
 * WeChat Mini Program share payload builder.
 *
 * Used by `onShareAppMessage` on any page that opts into sharing. Keeps
 * copy and image asset in one place so the brand stays consistent across
 * every share surface. The 5:4 aspect ratio matches WeChat's chat-bubble
 * thumbnail.
 */

export type ShareLocale = 'en' | 'zh';

const LANGUAGE_STORAGE_KEY = 'praxys-language';
type LanguagePref = 'auto' | 'en' | 'zh';

export function getLanguagePreference(): LanguagePref {
  const stored = wx.getStorageSync<LanguagePref | string>(LANGUAGE_STORAGE_KEY);
  if (stored === 'en' || stored === 'zh' || stored === 'auto') return stored;
  return 'auto';
}

export function setLanguagePreference(pref: LanguagePref): void {
  wx.setStorageSync(LANGUAGE_STORAGE_KEY, pref);
}

export interface ShareMessage {
  title: string;
  path: string;
  imageUrl: string;
}

export const SHARE_IMAGE_URL = '/assets/og-card-wechat.jpg';

export function getShareMessage(locale: ShareLocale, path?: string): ShareMessage {
  const title =
    locale === 'zh'
      ? '像专业选手一样训练 — 无论水平高低。'
      : 'Train like a pro. Whatever your level.';

  return {
    title,
    path: path && path.length > 0 ? path : '/pages/today/index',
    imageUrl: SHARE_IMAGE_URL,
  };
}

/**
 * Build a per-page share with custom title — used by Today/Training/Goal
 * to surface the user's actual training state ("Today: GO — Follow Plan",
 * "12 days to Marathon · 3:30:00 predicted") instead of the generic
 * brand tagline. WeChat caps share titles at ~32 Chinese chars / ~64
 * ASCII; we trim defensively.
 */
export function buildShareMessage(title: string, path: string): ShareMessage {
  const trimmed = title.length > 60 ? `${title.slice(0, 57)}…` : title;
  return {
    title: trimmed,
    path,
    imageUrl: SHARE_IMAGE_URL,
  };
}

/**
 * Moments (朋友圈) share payload. WeChat passes onShareTimeline a
 * different shape than onShareAppMessage — no path, only `query`. Use
 * the same brand image for the cover.
 */
export interface TimelineMessage {
  title: string;
  query: string;
  imageUrl: string;
}

export function buildTimelineMessage(title: string, query?: string): TimelineMessage {
  const trimmed = title.length > 60 ? `${title.slice(0, 57)}…` : title;
  return {
    title: trimmed,
    query: query ?? '',
    imageUrl: SHARE_IMAGE_URL,
  };
}

/**
 * Resolve the locale to use for share copy.
 *
 * Priority: explicit user preference (Settings → Language) → WeChat client
 * locale → fallback English. The user override is intentional — some
 * users want English share copy even if their phone is in zh, e.g. when
 * sharing to mixed-language groups.
 *
 * Native gives us wx.getAppBaseInfo() (added in libVersion 2.20.1, May
 * 2022) — the modern replacement for getSystemInfoSync().language. Older
 * clients lacking getAppBaseInfo fall back to getSystemInfoSync; oldest
 * clients without either degrade silently to English.
 */
export function detectShareLocale(): ShareLocale {
  const pref = getLanguagePreference();
  if (pref === 'en' || pref === 'zh') return pref;
  // Default to zh when locale is unknown — see utils/i18n.ts for rationale.
  // English locales (en_US, en_GB, …) still match `^en` and stay in en.
  try {
    const lang =
      typeof wx.getAppBaseInfo === 'function'
        ? wx.getAppBaseInfo().language ?? ''
        : (wx.getSystemInfoSync().language ?? '');
    return /^en/i.test(lang) ? 'en' : 'zh';
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[share] locale detection failed, defaulting to zh:', e);
    return 'zh';
  }
}
