import type { RecoveryData } from '@/types/api';
import { useScience, tsbZoneFromConfig } from '@/contexts/ScienceContext';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props {
  recovery: RecoveryData;
}

function scoreColor(value: number | undefined, thresholds = { green: 80, amber: 60 }): string {
  if (value == null) return 'text-muted-foreground';
  if (value >= thresholds.green) return 'text-primary';
  if (value >= thresholds.amber) return 'text-accent-amber';
  return 'text-destructive';
}

function trendArrow(pct: number | undefined): { arrow: string; color: string } {
  if (pct == null || Math.abs(pct) < 1) return { arrow: '\u2192', color: 'text-muted-foreground' };
  if (pct > 0) return { arrow: '\u2191', color: 'text-primary' };
  return { arrow: '\u2193', color: 'text-destructive' };
}

function MetricCard({
  label,
  value,
  suffix,
  colorClass,
  colorStyle,
  extra,
}: {
  label: string;
  value: string;
  suffix?: string;
  colorClass: string;
  colorStyle?: string;
  extra?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl bg-muted p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
        {label}
      </p>
      <div className="flex items-baseline gap-1">
        <span className={`text-3xl font-bold font-data ${colorClass}`} style={colorStyle ? { color: colorStyle } : undefined}>{value}</span>
        {suffix && <span className="text-sm text-muted-foreground">{suffix}</span>}
        {extra}
      </div>
    </div>
  );
}

export default function RecoveryPanel({ recovery }: Props) {
  const { tsbZones } = useScience();
  const tsbZone = tsbZoneFromConfig(recovery.tsb, tsbZones);
  const trend = trendArrow(recovery.hrv_trend_pct);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Recovery
        </CardTitle>
      </CardHeader>
      <CardContent>
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          label="Readiness"
          value={recovery.readiness != null ? String(recovery.readiness) : '--'}
          colorClass={scoreColor(recovery.readiness)}
        />
        <MetricCard
          label="HRV"
          value={recovery.hrv_ms != null ? String(recovery.hrv_ms) : '--'}
          suffix="ms"
          colorClass={recovery.hrv_ms != null ? 'text-foreground' : 'text-muted-foreground'}
          extra={
            <span className={`ml-1 text-lg font-bold ${trend.color}`}>{trend.arrow}</span>
          }
        />
        <MetricCard
          label="Sleep"
          value={recovery.sleep_score != null ? String(recovery.sleep_score) : '--'}
          colorClass={scoreColor(recovery.sleep_score)}
        />
        <MetricCard
          label="TSB"
          value={String(recovery.tsb)}
          colorClass=""
          colorStyle={tsbZone.color}
        />
      </div>
      </CardContent>
    </Card>
  );
}
