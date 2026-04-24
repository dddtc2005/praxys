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

export const SHARE_IMAGE_URL: string = shareImage;

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
 * page owns the onShareAppMessage callback.
 */
export function detectShareLocale(): ShareLocale {
  try {
    const lang = Taro.getSystemInfoSync().language ?? '';
    return /zh/i.test(lang) ? 'zh' : 'en';
  } catch {
    return 'en';
  }
}
