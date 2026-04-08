import type { RecoveryData } from '../types/api';
import { useScience, tsbZoneFromConfig } from '../contexts/ScienceContext';

interface Props {
  recovery: RecoveryData;
}

function scoreColor(value: number | undefined, thresholds = { green: 80, amber: 60 }): string {
  if (value == null) return 'text-text-muted';
  if (value >= thresholds.green) return 'text-accent-green';
  if (value >= thresholds.amber) return 'text-accent-amber';
  return 'text-accent-red';
}

function trendArrow(pct: number | undefined): { arrow: string; color: string } {
  if (pct == null || Math.abs(pct) < 1) return { arrow: '\u2192', color: 'text-text-muted' };
  if (pct > 0) return { arrow: '\u2191', color: 'text-accent-green' };
  return { arrow: '\u2193', color: 'text-accent-red' };
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
    <div className="rounded-xl bg-panel-light p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
        {label}
      </p>
      <div className="flex items-baseline gap-1">
        <span className={`text-3xl font-bold font-data ${colorClass}`} style={colorStyle ? { color: colorStyle } : undefined}>{value}</span>
        {suffix && <span className="text-sm text-text-muted">{suffix}</span>}
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
    <div className="rounded-2xl bg-panel p-5 sm:p-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
        Recovery
      </h3>
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
          colorClass={recovery.hrv_ms != null ? 'text-text-primary' : 'text-text-muted'}
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
    </div>
  );
}
