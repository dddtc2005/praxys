/**
 * Centralized chart color constants.
 * Recharts needs string color values — CSS var() works in most JSX props
 * but fails in SVG gradient stopColor. Keep hex constants here as the
 * single source of truth; they match the OKLCH --chart-* vars in index.css.
 */
export const chartColors = {
  fitness: '#00ff87',    // green — CTL, positive signals
  fatigue: '#ef4444',    // red — ATL, destructive
  form: '#3b82f6',       // blue — TSB, informational
  threshold: '#f59e0b',  // amber — warnings, CP target
  projection: '#8b5cf6', // purple — projections, recovery

  // Semantic aliases
  positive: '#00ff87',
  warning: '#f59e0b',
  negative: '#ef4444',

  // Chart furniture
  grid: '#1e293b',
  tick: '#64748b',
  tickLight: '#94a3b8',
  tooltipBg: 'oklch(0.18 0.02 264)',
  tooltipBorder: '#1e293b',
} as const;
