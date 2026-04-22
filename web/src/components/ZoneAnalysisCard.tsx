import type { ZoneDistribution, ZoneRange, DisplayConfig } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Trans, useLingui } from '@lingui/react/macro';
import { tDisplay } from '@/lib/display-labels';

interface Props {
  distribution: ZoneDistribution[];
  zoneRanges: ZoneRange[];
  theoryName: string;
  display?: DisplayConfig;
}

const ZONE_TEXT_COLORS = [
  'text-muted-foreground',
  'text-accent-blue/70',
  'text-accent-blue',
  'text-accent-amber',
  'text-destructive',
];

function getZoneTextColor(index: number, total: number) {
  const scaled = Math.round((index / Math.max(total - 1, 1)) * (ZONE_TEXT_COLORS.length - 1));
  return ZONE_TEXT_COLORS[scaled] ?? ZONE_TEXT_COLORS[0];
}

function formatRange(range: ZoneRange): string {
  if (range.upper == null) return `> ${range.lower}${range.unit}`;
  if (range.lower === 0) return `< ${range.upper}${range.unit}`;
  return `${range.lower}–${range.upper}${range.unit}`;
}

export default function ZoneAnalysisCard({ distribution, zoneRanges, theoryName, display }: Props) {
  const { t, i18n } = useLingui();
  const thresholdLabel = display ? `${display.threshold_abbrev}` : '';

  const rows = [...distribution].reverse();
  const ranges = [...zoneRanges].reverse();

  const alerts = distribution
    .filter((d) => d.target_pct != null && Math.abs(d.actual_pct - d.target_pct!) > 5)
    .map((d) => {
      const diff = d.actual_pct - d.target_pct!;
      const direction = diff > 0 ? t`above` : t`below`;
      return `${tDisplay(d.name, i18n)}: ${d.actual_pct}% (${Math.abs(diff)}pp ${direction} ${d.target_pct}% ${t`target`})`;
    });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <Trans>Zone Analysis</Trans> · {theoryName}
          </CardTitle>
          {thresholdLabel && (
            <span className="text-xs text-muted-foreground font-data">{thresholdLabel}</span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-center pb-2 mb-2 border-b border-border">
          <span className="w-20 text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Zone</Trans></span>
          <span className="flex-1 text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Range</Trans></span>
          <span className="w-14 text-right text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Actual</Trans></span>
          <span className="w-14 text-right text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Target</Trans></span>
        </div>

        <div className="space-y-1.5">
          {rows.map((d, i) => {
            const range = ranges[i];
            const colorClass = getZoneTextColor(distribution.length - 1 - i, distribution.length);
            return (
              <div key={d.name} className="flex items-center">
                <span className={`w-20 text-sm font-medium ${colorClass}`}>{tDisplay(d.name, i18n)}</span>
                <span className="flex-1 text-sm text-muted-foreground font-data">
                  {range ? formatRange(range) : ''}
                </span>
                <span className="w-14 text-right text-sm font-semibold font-data text-foreground">
                  {d.actual_pct}%
                </span>
                <span className="w-14 text-right text-sm font-data text-muted-foreground">
                  {d.target_pct != null ? `${d.target_pct}%` : '—'}
                </span>
              </div>
            );
          })}
        </div>

        {alerts.length > 0 && (
          <Alert className="mt-4 border-accent-amber/30 bg-accent-amber/5">
            <AlertDescription className="text-sm text-accent-amber">
              <Trans>Distribution deviates from target</Trans>: {alerts.join('; ')}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
