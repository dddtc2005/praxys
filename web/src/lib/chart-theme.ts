/**
 * Centralized chart color constants.
 * Recharts needs string hex values — CSS var() works in JSX props
 * but fails in SVG gradient stopColor. Keep hex constants here as the
 * single source of truth; they match the OKLCH --chart-* vars in index.css.
 *
 * Light colors are darkened for contrast on white backgrounds.
 * Dark colors are vivid/bright for contrast on dark backgrounds.
 */

interface ChartColorSet {
  fitness: string;
  fatigue: string;
  form: string;
  threshold: string;
  projection: string;
  positive: string;
  warning: string;
  negative: string;
  grid: string;
  tick: string;
  tickLight: string;
  tooltipBg: string;
  tooltipBorder: string;
}

const darkColors: ChartColorSet = {
  fitness: '#00ff87',
  fatigue: '#ef4444',
  form: '#3b82f6',
  threshold: '#f59e0b',
  projection: '#8b5cf6',

  positive: '#00ff87',
  warning: '#f59e0b',
  negative: '#ef4444',

  grid: '#1e293b',
  tick: '#64748b',
  tickLight: '#94a3b8',
  tooltipBg: '#1e293b',
  tooltipBorder: '#334155',
} as const;

const lightColors: ChartColorSet = {
  fitness: '#059669',
  fatigue: '#dc2626',
  form: '#2563eb',
  threshold: '#d97706',
  projection: '#7c3aed',

  positive: '#059669',
  warning: '#d97706',
  negative: '#dc2626',

  grid: '#e5e7eb',
  tick: '#6b7280',
  tickLight: '#4b5563',
  tooltipBg: '#ffffff',
  tooltipBorder: '#e5e7eb',
} as const;

export type ChartColors = ChartColorSet;

/** Get the chart color set for the current theme. */
export function getChartColors(isDark: boolean): ChartColors {
  return isDark ? darkColors : lightColors;
}

/**
 * Default export for backward compatibility and simple use cases
 * where you know the theme. Most components should use the
 * useChartColors() hook instead.
 */
export const chartColors = darkColors;
