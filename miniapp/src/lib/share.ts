/**
 * WeChat Mini Program share payload builder.
 *
 * Used by `onShareAppMessage` on any page that opts into sharing. Keeps
 * copy and image asset in one place so the brand stays consistent across
 * every share surface.
 *
 * The image is bundled locally (see miniapp/src/assets/og-card-wechat.jpg)
 * because WeChat's share renderer is most reliable with package-local
 * images. The 5:4 aspect ratio matches WeChat's chat-bubble thumbnail.
 */

export type ShareLocale = 'en' | 'zh';

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
