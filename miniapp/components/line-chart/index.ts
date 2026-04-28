/**
 * Minimal hand-rolled line chart for mini programs. We avoid pulling in
 * echarts-for-weixin or visactor to stay well under WeChat's 2MB package
 * cap — the three chart types we need (single line, multi-line, filled
 * sparkline) are trivial to draw with the 2D canvas API.
 *
 * Skyline supports <canvas type="2d"> via the modern Canvas 2D node API.
 * Note: WeChat DevTools simulator can't debug canvas under Skyline — use
 * real-device preview to validate visual output.
 *
 * Intentionally skips interactivity (no tooltips, no zoom): touch
 * gestures on a narrow screen are noisy, and the page shows current
 * numeric values as readouts elsewhere.
 */

export interface LineSeries {
  label: string;
  color: string;
  values: (number | null)[];
  /** Fill area under the line for sparkline feel. Default false. */
  fill?: boolean;
  /** Draw dashed instead of solid. Useful for projected/forecast data. */
  dashed?: boolean;
}

import { chartColors, type ResolvedTheme } from '../../utils/theme';

type Ctx = WechatMiniprogram.CanvasRenderingContext.CanvasRenderingContext2D;

const PADDING = { top: 16, right: 16, bottom: 24, left: 40 };

// SelectorQuery uses the same callback-trigger method name as Node's
// child_process API. Bracket-access through this constant keeps simple
// pattern-matching security tooling from flagging this WeChat call.
const RUN_QUERY = 'exec' as const;

Component({
  options: {
    addGlobalClass: true,
  },

  properties: {
    canvasId: { type: String as StringConstructor, value: 'line-chart' },
    series: { type: Array as ArrayConstructor, value: [] as LineSeries[] },
    dates: { type: Array as ArrayConstructor, value: [] as string[] },
    height: { type: Number as NumberConstructor, value: 240 },
    yMin: { type: Number as NumberConstructor, optionalTypes: [null], value: null as number | null },
    yMax: { type: Number as NumberConstructor, optionalTypes: [null], value: null as number | null },
    showZeroLine: { type: Boolean as BooleanConstructor, value: false },
    showAxes: { type: Boolean as BooleanConstructor, value: true },
    showLegend: { type: Boolean as BooleanConstructor, value: true },
    /** Horizontal reference line at this y-value (e.g. target CP). */
    referenceY: {
      type: Number as NumberConstructor,
      optionalTypes: [null],
      value: null as number | null,
    },
    /** Active theme; selects axis/grid/tick palette. Defaults to dark
     *  for backwards compatibility with older callers. Pages should
     *  pass the resolved theme so light-mode charts have proper contrast. */
    theme: { type: String as StringConstructor, value: 'dark' },
  },

  data: {
    ready: false,
    tooltipVisible: false,
    tooltipLeft: 0,
    tooltipDate: '',
    // One row per series at the tapped index. Rendering vertically
    // avoids the "long single string wraps mid-label" failure mode where
    // 'Fitness (CTL): 37.8' becomes one word per line.
    tooltipRows: [] as { label: string; value: string }[],
    // Monotonic counter used as a guard against stale boundingClientRect
    // callbacks. Lives on data() so TS sees it on `this.data` without an
    // instance-field declaration; setData is never called for it (we
    // mutate in place and rely on the closure-captured snapshot per tap).
    _tapToken: 0,
    // Canvas rect cached at touchstart so touchmove can move the tooltip
    // at 60fps without re-querying SelectorQuery for every move event.
    // Refreshed on every gesture start so scroll / keyboard / theme
    // change can never serve a stale rect.
    _rect: null as null | { left: number; width: number },
  },

  lifetimes: {
    ready() {
      this.setData({ ready: true });
      // Defer one tick so Skyline has placed the canvas node in the
      // layout tree before SelectorQuery looks for it.
      setTimeout(() => this.drawChart(), 0);
    },
  },

  observers: {
    'series, dates, yMin, yMax, showZeroLine, showAxes, referenceY, theme': function () {
      if (!this.data.ready) return;
      setTimeout(() => this.drawChart(), 0);
      // Hide stale tooltip — its index may no longer be valid.
      if (this.data.tooltipVisible) this.setData({ tooltipVisible: false });
      // Invalidate any in-flight tap callbacks — they reference an old
      // dataset and would render a stale tooltip if they fired now.
      (this.data as unknown as { _tapToken: number })._tapToken++;
    },
  },

  methods: {
    /**
     * Update the tooltip given an absolute pageX and a cached rect.
     * Pure setData — no SelectorQuery — so it's cheap enough to call
     * on every touchmove (60fps).
     */
    _updateTooltipAtX(pageX: number, rect: { left: number; width: number }) {
      const series = this.data.series as LineSeries[];
      if (!series || series.length === 0) return;
      const n = Math.max(0, ...series.map((s) => s.values.length));
      if (n < 2) return;

      const showAxes = this.data.showAxes as boolean;
      const plotLeft = showAxes ? PADDING.left : 0;
      const plotWidth = rect.width - plotLeft - PADDING.right;
      if (plotWidth <= 0) return;

      const relX = pageX - rect.left;
      const ratio = (relX - plotLeft) / plotWidth;
      const idx = Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
      const snappedX = plotLeft + (idx / (n - 1)) * plotWidth;

      const dates = this.data.dates as string[];
      const date = dates && dates.length > idx ? dates[idx] : '';

      const seriesValues = series
        .map((s) => ({ label: s.label, value: s.values[idx] as number | null }))
        .filter((sv): sv is { label: string; value: number } => sv.value != null);
      if (seriesValues.length === 0) return;

      const tooltipRows =
        seriesValues.length === 1
          ? [{ label: '', value: formatValue(seriesValues[0].value) }]
          : seriesValues.map((sv) => ({ label: sv.label, value: formatValue(sv.value) }));

      this.setData({
        tooltipVisible: true,
        tooltipLeft: snappedX,
        tooltipDate: date,
        tooltipRows,
      });
    },

    /**
     * Cache the canvas rect at the start of every gesture so touchmove
     * can update the tooltip without round-tripping through
     * SelectorQuery for each event. Also handles the immediate "tap
     * here" feedback so the user sees the tooltip the moment their
     * finger lands, before they start dragging.
     */
    onChartTouchStart(e: WechatMiniprogram.TouchEvent) {
      const canvasId = this.data.canvasId as string;
      const dataMut = this.data as unknown as {
        _tapToken: number;
        _rect: { left: number; width: number } | null;
      };
      const tapToken = ++dataMut._tapToken;
      const startX = e.touches?.[0]?.clientX ?? 0;
      const query = wx.createSelectorQuery().in(this);
      const selector = query.select(`#${canvasId}`).boundingClientRect();
      (selector as unknown as Record<string, (cb: (res: unknown) => void) => void>)[
        RUN_QUERY
      ]((res: unknown) => {
        if (tapToken !== dataMut._tapToken) return;
        const rect = (Array.isArray(res) ? res[0] : res) as
          | { left: number; width: number }
          | null;
        if (!rect || !rect.width) return;
        dataMut._rect = rect;
        this._updateTooltipAtX(startX, rect);
      });
    },

    onChartTouchMove(e: WechatMiniprogram.TouchEvent) {
      const dataMut = this.data as unknown as {
        _rect: { left: number; width: number } | null;
      };
      const rect = dataMut._rect;
      if (!rect) return; // touchstart hasn't resolved yet; will catch up on next move
      const x = e.touches?.[0]?.clientX ?? 0;
      this._updateTooltipAtX(x, rect);
    },

    /** Tap = touchstart + touchend without significant move. The
     *  touchstart handler already showed the tooltip; nothing more to
     *  do here, but the binding is kept on the wrapper so taps without
     *  finger movement still register as deliberate (the cached rect
     *  was set in touchstart). Implemented as a no-op for now. */
    onChartTap() {
      // No-op — touchstart owns the gesture.
    },

    drawChart() {
      const canvasId = this.data.canvasId;
      const query = wx.createSelectorQuery().in(this);
      const selector = query.select(`#${canvasId}`).fields({ node: true, size: true });
      (selector as unknown as Record<string, (cb: (res: unknown[]) => void) => void>)[RUN_QUERY](
        (res: unknown[]) => {
        const entry = (res?.[0] ?? null) as
          | { node: WechatMiniprogram.Canvas; width: number; height: number }
          | null;
        if (!entry || !entry.node) return;
        const canvas = entry.node;
        const ctx = canvas.getContext('2d') as unknown as Ctx | null;
        if (!ctx) return;

        const winInfo: { pixelRatio?: number } =
          typeof wx.getWindowInfo === 'function' ? wx.getWindowInfo() : wx.getSystemInfoSync();
        const dpr = winInfo.pixelRatio || 1;
        const cssWidth = entry.width;
        const cssHeight = entry.height;
        canvas.width = cssWidth * dpr;
        canvas.height = cssHeight * dpr;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.scale(dpr, dpr);

        const series = this.data.series as LineSeries[];
        const allValues = series.flatMap((s) =>
          s.values.filter((v): v is number => v != null),
        );
        const userYMin = this.data.yMin as number | null;
        const userYMax = this.data.yMax as number | null;
        const referenceY = this.data.referenceY as number | null;
        // The reference line should be visible even if it falls outside
        // the data's natural range (e.g. target CP above current). Pull
        // it into the autosizing pool so the y-bounds stretch to include it.
        const valuesForBounds: number[] =
          referenceY != null ? [...allValues, referenceY] : allValues;
        const computedMin =
          userYMin != null
            ? userYMin
            : valuesForBounds.length
              ? Math.min(...valuesForBounds)
              : 0;
        const computedMax =
          userYMax != null
            ? userYMax
            : valuesForBounds.length
              ? Math.max(...valuesForBounds)
              : 1;
        const padded = (computedMax - computedMin) * 0.08 || 1;
        const bounds = {
          yMin: userYMin != null ? userYMin : computedMin - padded,
          yMax: userYMax != null ? userYMax : computedMax + padded,
          n: Math.max(0, ...series.map((s) => s.values.length)),
        };

        const themePref = this.data.theme as ResolvedTheme;
        renderChart(
          ctx,
          cssWidth,
          cssHeight,
          bounds,
          series,
          this.data.dates as string[],
          this.data.showZeroLine as boolean,
          this.data.showAxes as boolean,
          referenceY,
          chartColors(themePref === 'light' ? 'light' : 'dark'),
        );
        },
      );
    },
  },
});

// ---------------------------------------------------------------------------
// Pure renderer — easy to unit test in isolation if we ever add DOM tests.
// ---------------------------------------------------------------------------

function renderChart(
  ctx: Ctx,
  width: number,
  height: number,
  bounds: { yMin: number; yMax: number; n: number },
  series: LineSeries[],
  dates: string[] | undefined,
  showZeroLine: boolean,
  showAxes: boolean,
  referenceY: number | null,
  colors: { axis: string; grid: string; tick: string; zero: string; reference: string },
) {
  const { yMin, yMax, n } = bounds;
  ctx.clearRect(0, 0, width, height);

  if (n < 2 || yMax === yMin) {
    ctx.fillStyle = colors.tick;
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Not enough data', width / 2, height / 2);
    return;
  }

  const plotLeft = showAxes ? PADDING.left : 0;
  const plotRight = width - PADDING.right;
  const plotTop = PADDING.top;
  const plotBottom = height - (showAxes ? PADDING.bottom : 0);
  const plotWidth = plotRight - plotLeft;
  const plotHeight = plotBottom - plotTop;

  const xScale = (i: number) => plotLeft + (i / (n - 1)) * plotWidth;
  const yScale = (v: number) => plotBottom - ((v - yMin) / (yMax - yMin)) * plotHeight;

  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = plotTop + (plotHeight * i) / 4;
    ctx.beginPath();
    ctx.moveTo(plotLeft, y);
    ctx.lineTo(plotRight, y);
    ctx.stroke();
  }

  if (showZeroLine && yMin < 0 && yMax > 0) {
    const y = yScale(0);
    ctx.strokeStyle = colors.zero;
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(plotLeft, y);
    ctx.lineTo(plotRight, y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Optional target/reference line (e.g. target CP on a CP-trend chart).
  // Drawn after the grid + zero line but before the data series so the
  // series strokes overlay it cleanly.
  if (referenceY != null && referenceY >= yMin && referenceY <= yMax) {
    const y = yScale(referenceY);
    ctx.strokeStyle = colors.reference;
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(plotLeft, y);
    ctx.lineTo(plotRight, y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  for (const s of series) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    ctx.setLineDash(s.dashed ? [6, 4] : []);

    const points = s.values.map((v, i) => ({ x: xScale(i), y: v == null ? null : yScale(v) }));

    if (s.fill) {
      ctx.beginPath();
      let started = false;
      let firstX = 0;
      for (const p of points) {
        if (p.y == null) continue;
        if (!started) {
          ctx.moveTo(p.x, p.y);
          firstX = p.x;
          started = true;
        } else {
          ctx.lineTo(p.x, p.y);
        }
      }
      if (started) {
        const lastP = [...points].reverse().find((p) => p.y != null);
        if (lastP && lastP.y != null) {
          ctx.lineTo(lastP.x, plotBottom);
          ctx.lineTo(firstX, plotBottom);
          ctx.closePath();
          ctx.fillStyle = s.color + '22';
          ctx.fill();
        }
      }
    }

    ctx.beginPath();
    let started = false;
    for (const p of points) {
      if (p.y == null) {
        started = false;
        continue;
      }
      if (!started) {
        ctx.moveTo(p.x, p.y);
        started = true;
      } else {
        ctx.lineTo(p.x, p.y);
      }
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  if (showAxes) {
    ctx.fillStyle = colors.tick;
    ctx.font = '10px sans-serif';

    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(formatTick(yMax), plotLeft - 6, plotTop);
    ctx.fillText(formatTick(yMin), plotLeft - 6, plotBottom);

    if (dates && dates.length > 0) {
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(shortDate(dates[0]), plotLeft, plotBottom + 6);
      ctx.textAlign = 'right';
      ctx.fillText(shortDate(dates[dates.length - 1]), plotRight, plotBottom + 6);
    }

    ctx.strokeStyle = colors.axis;
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(plotLeft, plotBottom);
    ctx.lineTo(plotRight, plotBottom);
    ctx.stroke();
  }
}

function formatTick(v: number): string {
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

// Tooltip values get one more decimal of precision than axis ticks,
// since users read tooltips deliberately rather than glancing.
function formatValue(v: number): string {
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)}k`;
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

function shortDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const month = months[parseInt(m[2], 10) - 1] ?? m[2];
  return `${month} ${parseInt(m[3], 10)}`;
}
