/**
 * Generate a branded share card via off-screen Canvas 2D, save to a
 * temp file, return the path. The caller passes that path as `imageUrl`
 * in onShareAppMessage so friends see a Praxys-branded card with the
 * user's actual training signal — not the static og-card.
 *
 * Canvas dimensions are 750×600 (WeChat share thumbnails crop to 5:4).
 * Custom fonts (Geist) don't load in WeChat canvas, so the wordmark
 * falls back to system sans-serif. OKLCH from app.scss is collapsed to
 * the hex equivalents below since canvas color parsing is conservative.
 */

export type SignalColor = 'green' | 'amber' | 'red';

export interface ShareCardInput {
  label: string;       // e.g. "EASY"
  subtitle: string;    // e.g. "Go Easy"
  reason: string;      // e.g. "HRV below threshold. Keep today easy…"
  color: SignalColor;
  // Locale switches the wordmark/footer copy. Pass 'en' for ASCII or
  // 'zh' for the Chinese label set. Defaults to 'en'.
  locale?: 'en' | 'zh';
}

const W = 750;
const H = 600;

const COLORS = {
  bg: '#faf9f5',
  text: '#15192a',
  textMuted: '#6b6b66',
  primary: '#1e8e5b',
  cobalt: '#2e71c6',
  green: '#1e8e5b',
  amber: '#f59e0b',
  red: '#d93a2c',
};

type Ctx = WechatMiniprogram.CanvasRenderingContext.CanvasRenderingContext2D;

interface CanvasImage {
  width: number;
  height: number;
  src: string;
  onload: (() => void) | null;
  onerror: ((e: unknown) => void) | null;
}

function loadImage(canvas: WechatMiniprogram.OffscreenCanvas, src: string): Promise<CanvasImage> {
  return new Promise((resolve, reject) => {
    const img = canvas.createImage() as unknown as CanvasImage;
    img.onload = () => resolve(img);
    img.onerror = (e: unknown) => reject(e);
    img.src = src;
  });
}

/**
 * Word-wrap a string into lines that each fit within `maxWidth`. Uses
 * ctx.measureText, so call after fillStyle/font are set. CJK falls back
 * to per-character wrapping since spaces aren't break opportunities.
 */
function wrapLines(
  ctx: Ctx,
  text: string,
  maxWidth: number,
  maxLines: number,
): string[] {
  if (!text) return [];
  // U+4E00..U+9FFF — the Unicode CJK Unified Ideographs block. Covers the
  // common Chinese characters used in Praxys signal copy; a hit means the
  // text has no space-delimited words, so we wrap per character instead.
  const isCjk = /[一-鿿]/.test(text);
  const tokens = isCjk ? Array.from(text) : text.split(/\s+/);
  const sep = isCjk ? '' : ' ';
  const lines: string[] = [];
  let current = '';

  for (const token of tokens) {
    const candidate = current ? current + sep + token : token;
    if (ctx.measureText(candidate).width <= maxWidth) {
      current = candidate;
    } else {
      if (current) lines.push(current);
      current = token;
      if (lines.length >= maxLines - 1) {
        // Last line — truncate to fit + ellipsis
        let truncated = current;
        while (ctx.measureText(truncated + '…').width > maxWidth && truncated.length > 1) {
          truncated = truncated.slice(0, -1);
        }
        lines.push(truncated + '…');
        return lines;
      }
    }
  }
  if (current) lines.push(current);
  return lines.slice(0, maxLines);
}

export async function generateShareCard(input: ShareCardInput): Promise<string> {
  const locale = input.locale ?? 'en';
  const canvas = wx.createOffscreenCanvas({ type: '2d', width: W, height: H });
  // Cast: WeChat's OffscreenCanvas getContext returns the wx 2D context;
  // we treat it as a Ctx for the standard methods.
  const ctx = canvas.getContext('2d') as unknown as Ctx;
  if (!ctx) throw new Error('Failed to acquire canvas 2D context');

  // Background
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, W, H);

  // Top accent bar — primary green strip
  ctx.fillStyle = COLORS.primary;
  ctx.fillRect(0, 0, W, 8);

  // Try to load and draw the brand mark; if it fails, skip and continue
  // (the card still works without the logo).
  const LOGO_X = 60;
  const LOGO_Y = 50;
  const LOGO_SIZE = 80;
  try {
    const logo = (await loadImage(canvas, '/assets/brand/mark.png')) as unknown as {
      width: number;
      height: number;
    };
    (ctx as unknown as { drawImage: (...args: unknown[]) => void }).drawImage(
      logo,
      LOGO_X,
      LOGO_Y,
      LOGO_SIZE,
      LOGO_SIZE,
    );
  } catch {
    // Continue without logo
  }

  // Pra<x>ys wordmark — text since canvas doesn't reliably load Geist
  // from a font file. System sans-serif still reads as "the brand".
  ctx.textBaseline = 'middle';
  const wordmarkX = LOGO_X + LOGO_SIZE + 20;
  const wordmarkY = LOGO_Y + LOGO_SIZE / 2;
  ctx.font = '500 64px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = COLORS.text;
  ctx.textAlign = 'left';
  ctx.fillText('Pra', wordmarkX, wordmarkY);
  const praWidth = ctx.measureText('Pra').width;
  ctx.fillStyle = COLORS.primary;
  ctx.fillText('x', wordmarkX + praWidth, wordmarkY);
  const xWidth = ctx.measureText('x').width;
  ctx.fillStyle = COLORS.text;
  ctx.fillText('ys', wordmarkX + praWidth + xWidth, wordmarkY);

  // "Today's signal" small label
  ctx.textBaseline = 'top';
  ctx.font = '500 24px -apple-system, BlinkMacSystemFont, sans-serif';
  ctx.fillStyle = COLORS.textMuted;
  ctx.fillText(locale === 'zh' ? '今日训练信号' : "TODAY'S SIGNAL", LOGO_X, 200);

  // Big signal label in signal color
  const signalColor =
    input.color === 'green' ? COLORS.green : input.color === 'amber' ? COLORS.amber : COLORS.red;
  ctx.fillStyle = signalColor;
  ctx.font = 'bold 132px -apple-system, BlinkMacSystemFont, sans-serif';
  ctx.fillText(input.label || '—', LOGO_X, 230);

  // Subtitle in same signal color
  ctx.fillStyle = signalColor;
  ctx.font = '600 36px -apple-system, BlinkMacSystemFont, sans-serif';
  ctx.fillText(input.subtitle || '', LOGO_X, 380);

  // Reason text — wrapped
  ctx.fillStyle = COLORS.text;
  ctx.font = '400 26px -apple-system, BlinkMacSystemFont, sans-serif';
  const reasonY = 430;
  const reasonMaxWidth = W - LOGO_X * 2;
  const reasonLines = wrapLines(ctx, input.reason || '', reasonMaxWidth, 2);
  reasonLines.forEach((line, i) => {
    ctx.fillText(line, LOGO_X, reasonY + i * 36);
  });

  // Footer
  ctx.fillStyle = COLORS.textMuted;
  ctx.font = '500 22px -apple-system, BlinkMacSystemFont, sans-serif';
  ctx.fillText(
    locale === 'zh' ? 'praxys.run · 数据驱动的训练' : 'praxys.run · power-based training',
    LOGO_X,
    H - 60,
  );

  // Convert to temp file
  return new Promise<string>((resolve, reject) => {
    wx.canvasToTempFilePath({
      canvas: canvas as unknown as WechatMiniprogram.Canvas,
      width: W,
      height: H,
      destWidth: W,
      destHeight: H,
      fileType: 'jpg',
      quality: 0.92,
      success: (res) => resolve(res.tempFilePath),
      fail: (err) => reject(err),
    });
  });
}
