import { useMemo } from 'react';
import { getChartColors, type ChartColors } from '@/lib/chart-theme';
import { useTheme } from '@/hooks/useTheme';

export function useChartColors(): ChartColors {
  const { resolved } = useTheme();
  return useMemo(() => getChartColors(resolved === 'dark'), [resolved]);
}
