/**
 * WeChat Mini Program share payload builder.
 *
 * Used by `onShareAppMessage` on any page that opts into sharing. Keeps
 * copy and image asset in one place so the brand stays consistent across
 * every share surface.
 *
 * The image is bundled via webpack (see miniapp/src/assets/og-card-wechat.jpg)
 * so Taro can rewrite the path into whatever the emitted bundle uses. WeChat's
 * share renderer is most reliable with package-local images, and the 5:4
 * aspect ratio matches WeChat's chat-bubble thumbnail.
 */

import Taro from '@tarojs/taro';

import shareImage from '../assets/og-card-wechat.jpg';

export type ShareLocale = 'en' | 'zh';

export interface ShareMessage {
  title: string;
  path: string;
  imageUrl: string;
}

export const SHARE_IMAGE_URL = shareImage;

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
 * Best-effort WeChat locale detection for the share sheet.
 *
 * Taro.getSystemInfoSync().language is deprecated in newer WeChat clients
 * but still ships `language` today. The try/catch is here so a future
 * removal degrades gracefully to English instead of crashing whichever
 * page owns the onShareAppMessage callback. The console.warn makes the
 * regression visible in devtools so we're not debugging a "why are zh
 * users seeing English share titles" ticket in the dark.
 */
export function detectShareLocale(): ShareLocale {
  try {
    const lang = Taro.getSystemInfoSync().language ?? '';
    return /zh/i.test(lang) ? 'zh' : 'en';
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('[share] locale detection failed, falling back to en:', e);
    return 'en';
  }
}
