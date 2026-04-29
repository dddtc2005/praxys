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
}

const W = 750;
const H = 750;

// Matches mini program app.scss dark theme tokens + signal colors.
const C = {
  bg: '#0d1220',
  surface: '#161b2e',
  border: '#1f2536',
  text: '#e8ebf0',
  muted: '#8b93a7',
  primary: '#00ff87',
  amber: '#f59e0b',
  red: '#ef4444',
  wordmarkX: '#00ff87', // green 'x' in Praxys
};

function signalHex(color: SignalColor): string {
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
  const signalColor = signalHex(input.color);

  const canvas = wx.createOffscreenCanvas({ type: '2d', width: W, height: H });
  const ctx = canvas.getContext('2d') as unknown as Ctx;
  if (!ctx) throw new Error('Failed to acquire canvas 2D context');

  const ext = ctx as unknown as WxCtxExt & Ctx;

  // ── Background ──────────────────────────────────────────────────────────
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, W, H);

  // Subtle noise/texture — thin horizontal lines give a data-terminal feel.
  ctx.strokeStyle = '#ffffff06';
  ctx.lineWidth = 1;
  for (let y = 0; y < H; y += 18) {
    ctx.beginPath();
    ext.moveTo(0, y);
    ext.lineTo(W, y);
    ctx.stroke();
  }

  // ── Top bar: brand mark + wordmark ───────────────────────────────────────
  const MARK_X = 40;
  const MARK_Y = 40;
  const MARK_SIZE = 56;
  try {
    const logo = (await loadImage(canvas, '/assets/brand/mark.png')) as unknown as {
      width: number; height: number;
    };
    (ctx as unknown as { drawImage: (...a: unknown[]) => void }).drawImage(
      logo, MARK_X, MARK_Y, MARK_SIZE, MARK_SIZE,
    );
  } catch { /* continue without mark */ }

  // Wordmark "Pra x ys"
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

  // ── Signal circle — centered in the upper half ──────────────────────────
  const CX = W / 2;
  const CY = 330; // slightly above vertical center
  const R = 155;  // radius, matches ~240rpx at 2× density

  drawSignalCircle(ctx, CX, CY, R, signalColor);

  // Signal label inside the circle (EASY / GO / REST / etc.)
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.fillStyle = signalColor;
  // Adjust font size to fit — longer labels use smaller font.
  const label = input.label || '—';
  const labelSize = label.length <= 3 ? 96 : label.length <= 5 ? 76 : 60;
  ctx.font = `700 ${labelSize}px -apple-system, BlinkMacSystemFont, system-ui, sans-serif`;
  ctx.fillText(label, CX, CY);

  // ── Subtitle below circle ────────────────────────────────────────────────
  ctx.textBaseline = 'top';
  ctx.textAlign = 'center';
  ctx.font = '600 38px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = signalColor;
  ctx.fillText(input.subtitle || '', CX, CY + R + 32);

  // ── Reason text — wrapped, centered ────────────────────────────────────
  ctx.font = '400 26px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.muted;
  const reasonMaxWidth = W - 120;
  const reasonLines = wrapLines(ctx, input.reason || '', reasonMaxWidth, 2);
  const reasonStartY = CY + R + 86;
  reasonLines.forEach((line, i) => {
    ctx.fillText(line, CX, reasonStartY + i * 38);
  });

  // ── Divider ──────────────────────────────────────────────────────────────
  const divY = H - 100;
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ext.moveTo(40, divY);
  ext.lineTo(W - 40, divY);
  ctx.stroke();

  // ── Footer: tagline (left) + URL (right) ─────────────────────────────────
  ctx.textBaseline = 'middle';
  ctx.font = '400 22px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.muted;
  const footerY = divY + 38;
  ctx.textAlign = 'left';
  ctx.fillText(
    locale === 'zh' ? '像专业选手一样训练，无论水平高低。' : 'Train like a pro. Whatever your level.',
    40,
    footerY,
  );
  ctx.textAlign = 'right';
  ctx.fillStyle = C.primary;
  ctx.font = '500 22px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillText('praxys.run', W - 40, footerY);

  // ── Bottom accent bar ─────────────────────────────────────────────────────
  ctx.fillStyle = C.primary;
  ctx.fillRect(0, H - 6, W, 6);

  return new Promise<string>((resolve, reject) => {
    wx.canvasToTempFilePath({
      canvas: canvas as unknown as WechatMiniprogram.Canvas,
      width: W, height: H, destWidth: W, destHeight: H,
      fileType: 'jpg', quality: 0.92,
      success: (res) => resolve(res.tempFilePath),
      fail: (err) => reject(err),
    });
  });
}
