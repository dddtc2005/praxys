/**
 * Branded signal share card — rendered to an off-screen Canvas 2D and
 * saved to a temp file so the user can long-press → "Save image".
 *
 * Design: dark background, centered signal circle identical to the
 * mini program's pulsing circle (static glow drawn with canvas), the
 * signal label and subtitle, reason text, and Praxys wordmark.
 *
 * 750×750 — square crops better across WeChat's chat bubble, Moments
 * cover, and iOS/Android native share previews.
 */

export type SignalColor = 'green' | 'amber' | 'red';

export interface ShareCardInput {
  label: string;
  subtitle: string;
  reason: string;
  color: SignalColor;
  locale?: 'en' | 'zh';
  /** 'dark' (default) or 'light' — card adapts to the user's active theme. */
  theme?: 'dark' | 'light';
}

const W = 750;
const H = 750;

// Dark theme palette — dark bg, bright accent.
const DARK = {
  bg: '#0d1220',
  border: '#1f2536',
  text: '#e8ebf0',
  muted: '#8b93a7',
  primary: '#00ff87',
  amber: '#f59e0b',
  red: '#ef4444',
  wordmarkX: '#00ff87',
  cta: '#0d1220', // text on accent bar
};

// Light theme palette — cream bg, darker accent.
const LIGHT = {
  bg: '#faf9f5',
  border: '#dbd6c7',
  text: '#15192a',
  muted: '#6b6b66',
  primary: '#1e8e5b',
  amber: '#d97706',
  red: '#d93a2c',
  wordmarkX: '#1e8e5b',
  cta: '#ffffff', // text on accent bar
};

function getC(theme: 'dark' | 'light') {
  return theme === 'light' ? LIGHT : DARK;
}

function signalHex(color: SignalColor, C: typeof DARK): string {
  if (color === 'amber') return C.amber;
  if (color === 'red') return C.red;
  return C.primary; // green
}

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

function wrapLines(ctx: Ctx, text: string, maxWidth: number, maxLines: number): string[] {
  if (!text) return [];
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

interface WxGradient { addColorStop(offset: number, color: string): void; }
type WxCtxExt = {
  createRadialGradient(x0: number, y0: number, r0: number, x1: number, y1: number, r1: number): WxGradient;
  arc(x: number, y: number, r: number, s: number, e: number): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
};

/** Draw the signal circle + glow, mirroring the mini program's signal-circle design. */
function drawSignalCircle(ctx: Ctx, cx: number, cy: number, r: number, color: string) {
  const ext = ctx as unknown as WxCtxExt & Ctx;
  const hex = color;

  // Outer diffuse glow.
  const glowGrad = ext.createRadialGradient(cx, cy, 0, cx, cy, r * 2);
  glowGrad.addColorStop(0, hex + '30');
  glowGrad.addColorStop(1, hex + '00');
  ctx.fillStyle = glowGrad as unknown as string;
  ctx.beginPath();
  ext.arc(cx, cy, r * 2, 0, Math.PI * 2);
  ctx.fill();

  // Inner filled circle.
  const innerGrad = ext.createRadialGradient(cx, cy, 0, cx, cy, r);
  innerGrad.addColorStop(0, hex + '20');
  innerGrad.addColorStop(1, hex + '08');
  ctx.fillStyle = innerGrad as unknown as string;
  ctx.beginPath();
  ext.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();

  // Stroke ring.
  ctx.strokeStyle = hex + '55';
  ctx.lineWidth = 5;
  ctx.beginPath();
  ext.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.stroke();
}

export async function generateShareCard(input: ShareCardInput): Promise<string> {
  const locale = input.locale ?? 'en';
  const cardTheme = input.theme ?? 'dark';
  const C = getC(cardTheme);
  const signalColor = signalHex(input.color, C);

  // Scale up by device pixel ratio for retina sharpness (capped at 3×).
  const DPR = Math.min(
    ((typeof wx.getWindowInfo === 'function' ? wx.getWindowInfo() : wx.getSystemInfoSync()) as
      { pixelRatio?: number }).pixelRatio ?? 2,
    3,
  );
  const CW = W * DPR;
  const CH = H * DPR;

  const canvas = wx.createOffscreenCanvas({ type: '2d', width: CW, height: CH });
  const ctx = canvas.getContext('2d') as unknown as Ctx;
  if (!ctx) throw new Error('Failed to acquire canvas 2D context');
  ctx.scale(DPR, DPR);

  const ext = ctx as unknown as WxCtxExt & Ctx;
  const drawImage = ctx as unknown as { drawImage: (...a: unknown[]) => void };

  // ── Background ─────────────────────────────────────────────────────────
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, W, H);
  // No scan-line texture — it creates visible horizontal artifacts on JPEG.

  // ── Top bar: brand mark + wordmark (left), QR code (right) ────────────
  const MARK_X = 40;
  const MARK_Y = 40;
  const MARK_SIZE = 56;
  try {
    const logo = (await loadImage(canvas, '/assets/brand/mark.png')) as unknown as object;
    drawImage.drawImage(logo, MARK_X, MARK_Y, MARK_SIZE, MARK_SIZE);
  } catch { /* continue without mark */ }

  ctx.textBaseline = 'middle';
  ctx.font = '500 52px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  const WMX = MARK_X + MARK_SIZE + 16;
  const WMY = MARK_Y + MARK_SIZE / 2;
  ctx.fillStyle = C.text;
  ctx.textAlign = 'left';
  ctx.fillText('Pra', WMX, WMY);
  const praW = ctx.measureText('Pra').width;
  ctx.fillStyle = C.wordmarkX;
  ctx.fillText('x', WMX + praW, WMY);
  const xW = ctx.measureText('x').width;
  ctx.fillStyle = C.text;
  ctx.fillText('ys', WMX + praW + xW, WMY);

  // QR code — upper-right corner, aligned with the wordmark row.
  // Two pre-built assets: black modules on transparent (light theme),
  // white modules on transparent (dark theme). No runtime pixel manipulation.
  const QR_SIZE = 68;
  const QR_X = W - 40 - QR_SIZE;
  const QR_Y = MARK_Y + (MARK_SIZE - QR_SIZE) / 2;
  const qrAsset = cardTheme === 'dark'
    ? '/assets/qr-praxys-prod-dark.png'
    : '/assets/qr-praxys-prod.png';
  try {
    const qr = (await loadImage(canvas, qrAsset)) as unknown as object;
    drawImage.drawImage(qr, QR_X, QR_Y, QR_SIZE, QR_SIZE);
  } catch { /* no QR asset — skip silently */ }

  // ── Signal circle ───────────────────────────────────────────────────────
  const CX = W / 2;
  const CY = 315;
  const R = 148;
  drawSignalCircle(ctx, CX, CY, R, signalColor);

  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.fillStyle = signalColor;
  const label = input.label || '—';
  // Larger label sizes (+10px each tier)
  const labelSize = label.length <= 3 ? 108 : label.length <= 5 ? 86 : 68;
  ctx.font = `700 ${labelSize}px -apple-system, BlinkMacSystemFont, system-ui, sans-serif`;
  ctx.fillText(label, CX, CY);

  // ── Subtitle ────────────────────────────────────────────────────────────
  ctx.textBaseline = 'top';
  ctx.textAlign = 'center';
  ctx.font = '600 44px -apple-system, BlinkMacSystemFont, system-ui, sans-serif'; // was 36
  ctx.fillStyle = signalColor;
  ctx.fillText(input.subtitle || '', CX, CY + R + 28);

  // ── Reason text (wrapped, centered) ────────────────────────────────────
  ctx.font = '400 30px -apple-system, BlinkMacSystemFont, system-ui, sans-serif'; // was 25
  ctx.fillStyle = C.muted;
  const reasonLines = wrapLines(ctx, input.reason || '', W - 120, 2);
  const REASON_LINE_H = 42;
  const reasonY0 = CY + R + 86;
  reasonLines.forEach((line, i) => ctx.fillText(line, CX, reasonY0 + i * REASON_LINE_H));

  // ── Divider — positioned dynamically so reason text never overlaps it ───
  const BAR_H = 46;
  // Bottom of last reason line (font size 30, textBaseline 'top' → +32px)
  const reasonEndY = reasonLines.length > 0
    ? reasonY0 + (reasonLines.length - 1) * REASON_LINE_H + 32
    : reasonY0 - 20;
  // Always at least 20px below reason, but keep footer legible above accent bar
  const divY = Math.max(reasonEndY + 20, H - BAR_H - 110);
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ext.moveTo(40, divY);
  ext.lineTo(W - 40, divY);
  ctx.stroke();

  // ── Footer: tagline left, praxys.run right, same line ──────────────────
  const footerY = divY + 36;
  ctx.textBaseline = 'middle';
  ctx.font = '400 21px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.muted;
  ctx.textAlign = 'left';
  ctx.fillText(
    locale === 'zh' ? '像专业选手一样训练，无论水平高低。' : 'Train like a pro. Whatever your level.',
    40, footerY,
  );
  ctx.textAlign = 'right';
  ctx.fillStyle = C.primary;
  ctx.font = '500 21px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillText('praxys.run', W - 40, footerY);

  // ── Accent bar with CTA ──────────────────────────────────────────────────
  ctx.fillStyle = C.primary;
  ctx.fillRect(0, H - BAR_H, W, BAR_H);
  ctx.font = '500 20px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.cta;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(locale === 'zh' ? '长按图片转发' : 'Long press to share', W / 2, H - BAR_H / 2);

  return new Promise<string>((resolve, reject) => {
    wx.canvasToTempFilePath({
      canvas: canvas as unknown as WechatMiniprogram.Canvas,
      width: CW, height: CH, destWidth: CW, destHeight: CH,
      fileType: 'jpg', quality: 0.92,
      success: (res) => resolve(res.tempFilePath),
      fail: (err) => reject(err),
    });
  });
}
