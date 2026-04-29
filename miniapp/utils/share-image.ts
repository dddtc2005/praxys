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

  // Scale up by device pixel ratio so the output is sharp on retina screens.
  // Capped at 3 — above that the JPEG is oversized for chat bubble display.
  const DPR = Math.min(
    ((typeof wx.getWindowInfo === 'function' ? wx.getWindowInfo() : wx.getSystemInfoSync()) as
      { pixelRatio?: number }).pixelRatio ?? 2,
    3,
  );
  const CW = W * DPR; // physical canvas pixels
  const CH = H * DPR;

  const canvas = wx.createOffscreenCanvas({ type: '2d', width: CW, height: CH });
  const ctx = canvas.getContext('2d') as unknown as Ctx;
  if (!ctx) throw new Error('Failed to acquire canvas 2D context');
  ctx.scale(DPR, DPR); // all drawing commands use logical 750×750

  const ext = ctx as unknown as WxCtxExt & Ctx;
  const drawImage = ctx as unknown as { drawImage: (...a: unknown[]) => void };

  // ── Background ──────────────────────────────────────────────────────────
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, W, H);

  // Subtle horizontal scan-line texture for data-terminal aesthetic.
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

  // ── Signal circle ────────────────────────────────────────────────────────
  const CX = W / 2;
  const CY = 320;
  const R = 148;

  drawSignalCircle(ctx, CX, CY, R, signalColor);

  // Signal label inside circle.
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.fillStyle = signalColor;
  const label = input.label || '—';
  const labelSize = label.length <= 3 ? 94 : label.length <= 5 ? 74 : 58;
  ctx.font = `700 ${labelSize}px -apple-system, BlinkMacSystemFont, system-ui, sans-serif`;
  ctx.fillText(label, CX, CY);

  // ── Subtitle ─────────────────────────────────────────────────────────────
  ctx.textBaseline = 'top';
  ctx.textAlign = 'center';
  ctx.font = '600 36px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = signalColor;
  ctx.fillText(input.subtitle || '', CX, CY + R + 28);

  // ── Reason (wrapped) ─────────────────────────────────────────────────────
  ctx.font = '400 25px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.muted;
  const reasonLines = wrapLines(ctx, input.reason || '', W - 120, 2);
  const reasonY0 = CY + R + 76;
  reasonLines.forEach((line, i) => ctx.fillText(line, CX, reasonY0 + i * 36));

  // ── Editorial strip above divider ────────────────────────────────────────
  const divY = H - 148; // moved up to fit taller accent bar
  ctx.font = '500 14px -apple-system, system-ui, monospace, sans-serif';
  ctx.fillStyle = C.primary + '50'; // 32% opacity accent
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const strip = locale === 'zh' ? '训练信号  ·  PRAXYS.RUN' : 'TRAINING SIGNAL  ·  PRAXYS.RUN';
  ctx.fillText(strip, W / 2, divY - 22);

  // ── Divider ───────────────────────────────────────────────────────────────
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ext.moveTo(40, divY);
  ext.lineTo(W - 40, divY);
  ctx.stroke();

  // ── Footer: tagline (left) + QR code (right) ─────────────────────────────
  ctx.textBaseline = 'middle';
  ctx.font = '400 21px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.muted;
  const footerY = divY + 30;
  ctx.textAlign = 'left';
  ctx.fillText(
    locale === 'zh' ? '像专业选手一样训练，无论水平高低。' : 'Train like a pro. Whatever your level.',
    40,
    footerY,
  );
  // praxys.run URL (visible when QR not available)
  ctx.textAlign = 'left';
  ctx.font = '400 18px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.muted;
  ctx.fillText('praxys.run', 40, footerY + 28);

  // QR code (bottom-right, above accent bar)
  const QR_SIZE = 72;
  const QR_X = W - 40 - QR_SIZE;
  const QR_Y = H - 46 - QR_SIZE; // just above accent bar
  try {
    const qr = (await loadImage(canvas, '/assets/qr-praxys.png')) as unknown as object;
    // White background pad so QR is always readable regardless of card bg.
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(QR_X - 4, QR_Y - 4, QR_SIZE + 8, QR_SIZE + 8);
    drawImage.drawImage(qr, QR_X, QR_Y, QR_SIZE, QR_SIZE);
  } catch { /* no QR asset — silently skip */ }

  // ── Accent bar — taller with "长按图片转发" CTA ─────────────────────────
  const BAR_H = 46;
  ctx.fillStyle = C.primary;
  ctx.fillRect(0, H - BAR_H, W, BAR_H);
  ctx.font = '500 19px -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
  ctx.fillStyle = C.bg;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(locale === 'zh' ? '长按图片转发' : 'Long press to share', 24, H - BAR_H / 2);

  return new Promise<string>((resolve, reject) => {
    wx.canvasToTempFilePath({
      canvas: canvas as unknown as WechatMiniprogram.Canvas,
      width: CW, height: CH,
      destWidth: CW, destHeight: CH,
      fileType: 'jpg', quality: 0.92,
      success: (res) => resolve(res.tempFilePath),
      fail: (err) => reject(err),
    });
  });
}
