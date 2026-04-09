import type { RecoveryData, RecoveryTheoryMeta, RecoveryAnalysis } from '@/types/api';
import { useScience, tsbZoneFromConfig } from '@/contexts/ScienceContext';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ScienceNote from '@/components/ScienceNote';
import { useChartColors } from '@/hooks/useChartColors';

interface Props {
  recovery: RecoveryData;
  theoryMeta?: RecoveryTheoryMeta;
  analysis?: RecoveryAnalysis;
}

const STATUS_CONFIG = {
  fresh: { label: 'Fresh', class: 'text-primary', badgeBg: 'bg-primary/10 text-primary', desc: 'HRV above baseline' },
  normal: { label: 'Normal', class: 'text-foreground', badgeBg: 'bg-muted text-muted-foreground', desc: 'HRV within normal range' },
  fatigued: { label: 'Fatigued', class: 'text-destructive', badgeBg: 'bg-destructive/10 text-destructive', desc: 'HRV below threshold' },
} as const;

const TREND_LABELS = {
  stable: { symbol: '\u2192', label: 'Stable', class: 'text-muted-foreground' },
  improving: { symbol: '\u2191', label: 'Improving', class: 'text-primary' },
  declining: { symbol: '\u2193', label: 'Declining', class: 'text-destructive' },
} as const;

const RHR_LABELS = {
  stable: { label: 'Normal', class: 'text-muted-foreground' },
  elevated: { label: 'Elevated', class: 'text-destructive' },
  low: { label: 'Low', class: 'text-primary' },
} as const;

export default function RecoveryPanel({ recovery, theoryMeta, analysis }: Props) {
  const { tsbZones } = useScience();
  const tsbZone = tsbZoneFromConfig(recovery.tsb, tsbZones);
  const chartColors = useChartColors();

  const headerTitle = theoryMeta
    ? `Recovery \u00b7 ${theoryMeta.name}`
    : 'Recovery';

  const status = analysis?.status ?? 'normal';
  const statusCfg = STATUS_CONFIG[status];
  const hrv = analysis?.hrv;
  const trendCfg = hrv ? TREND_LABELS[hrv.trend] : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {headerTitle}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Status — categorical output from Kiviniemi protocol */}
        <div className="rounded-xl bg-muted p-4 mb-3">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Recovery Status
            </p>
            <Badge className={`text-[10px] ${statusCfg.badgeBg} border-0`}>
              {statusCfg.label}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">{statusCfg.desc}</p>
        </div>

        {/* HRV Analysis — Plews protocol */}
        {hrv && (
          <div className="mb-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              HRV Analysis
              <span className="text-muted-foreground/50 font-normal ml-1">(ln RMSSD)</span>
            </p>
            <div className="grid grid-cols-3 gap-2">
              {/* Today's value */}
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Today</p>
                <span className={`text-lg font-bold font-data ${statusCfg.class}`}>
                  {hrv.today_ln.toFixed(2)}
                </span>
                {hrv.today_ms != null && (
                  <span className="text-[9px] text-muted-foreground ml-1">
                    ({hrv.today_ms} ms)
                  </span>
                )}
              </div>
              {/* Baseline / Threshold */}
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Baseline</p>
                <span className="text-lg font-bold font-data text-foreground">
                  {hrv.baseline_mean_ln.toFixed(2)}
                </span>
                <span className="text-[9px] text-muted-foreground ml-1">
                  {'\u00b1'}{hrv.baseline_sd_ln.toFixed(2)}
                </span>
              </div>
              {/* 7-day trend */}
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">7d Trend</p>
                {trendCfg && (
                  <div className="flex items-baseline gap-1">
                    <span className={`text-lg font-bold ${trendCfg.class}`}>{trendCfg.symbol}</span>
                    <span className={`text-xs font-semibold ${trendCfg.class}`}>{trendCfg.label}</span>
                  </div>
                )}
              </div>
            </div>
            {/* CV indicator */}
            {hrv.rolling_cv > 0 && (
              <div className="flex items-center gap-2 mt-2">
                <span className="text-[9px] uppercase tracking-wider text-muted-foreground">CV</span>
                <span className={`text-xs font-data font-semibold ${hrv.rolling_cv > 10 ? 'text-accent-amber' : 'text-muted-foreground'}`}>
                  {hrv.rolling_cv.toFixed(1)}%
                </span>
                {hrv.rolling_cv > 10 && (
                  <span className="text-[9px] text-accent-amber">High variability</span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Informational signals — not part of the HRV model */}
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
          Other Signals
        </p>
        <div className="grid grid-cols-3 gap-2 mb-3">
          <div className="rounded-lg bg-muted p-3">
            <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1" style={{ color: `${chartColors.fitness}99` }}>
              Sleep
            </p>
            <span className={`text-lg font-bold font-data ${
              (analysis?.sleep_score ?? recovery.sleep_score ?? 0) >= 80 ? 'text-primary' :
              (analysis?.sleep_score ?? recovery.sleep_score ?? 0) >= 60 ? 'text-accent-amber' :
              (analysis?.sleep_score ?? recovery.sleep_score) != null ? 'text-destructive' : 'text-muted-foreground'
            }`}>
              {analysis?.sleep_score ?? recovery.sleep_score ?? '--'}
            </span>
          </div>
          <div className="rounded-lg bg-muted p-3">
            <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1" style={{ color: `${chartColors.threshold}99` }}>
              RHR
            </p>
            <div className="flex items-baseline gap-1">
              <span className="text-lg font-bold font-data text-foreground">
                {analysis?.resting_hr ?? '--'}
              </span>
              {analysis?.resting_hr != null && (
                <span className="text-[9px] text-muted-foreground">bpm</span>
              )}
            </div>
            {analysis?.rhr_trend && (
              <span className={`text-[9px] ${RHR_LABELS[analysis.rhr_trend].class}`}>
                {RHR_LABELS[analysis.rhr_trend].label}
              </span>
            )}
          </div>
          <div className="rounded-lg bg-muted p-3">
            <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1" style={{ color: tsbZone.color }}>
              TSB
            </p>
            <span className="text-lg font-bold font-data" style={{ color: tsbZone.color }}>
              {recovery.tsb.toFixed(1)}
            </span>
          </div>
        </div>

        <ScienceNote
          text="Recovery status is determined by comparing today's ln(RMSSD) to your personal baseline mean minus 1 standard deviation (Kiviniemi et al, 2007). The 7-day trend and coefficient of variation (CV) are monitored per Plews et al (2012) — a declining trend or CV above 10% signals autonomic disturbance. Sleep, RHR, and TSB are shown as informational context but are not combined into a weighted score."
          sourceUrl="https://link.springer.com/article/10.1007/s00421-012-2354-4"
          sourceLabel="Plews et al (2012)"
        />
      </CardContent>
    </Card>
  );
}
