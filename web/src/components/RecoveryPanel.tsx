import type { RecoveryData, RecoveryTheoryMeta, RecoveryAnalysis, RecoveryStatus } from '@/types/api';
import { useScience, tsbZoneFromConfig } from '@/contexts/ScienceContext';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import ScienceNote from '@/components/ScienceNote';
import { Trans, useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';
import { useLocale } from '@/contexts/LocaleContext';

interface Props {
  recovery: RecoveryData;
  theoryMeta?: RecoveryTheoryMeta;
  analysis?: RecoveryAnalysis;
}

const STATUS_CONFIG: Record<string, { label: MessageDescriptor; class: string; badgeBg: string; desc: MessageDescriptor }> = {
  fresh: { label: msg`Fresh`, class: 'text-primary', badgeBg: 'bg-primary/10 text-primary', desc: msg`HRV above baseline (Plews SWC)` },
  normal: { label: msg`Normal`, class: 'text-foreground', badgeBg: 'bg-muted text-muted-foreground', desc: msg`HRV within normal range` },
  fatigued: { label: msg`Fatigued`, class: 'text-destructive', badgeBg: 'bg-destructive/10 text-destructive', desc: msg`HRV below threshold (Kiviniemi)` },
  insufficient_data: { label: msg`No Data`, class: 'text-muted-foreground', badgeBg: 'bg-muted text-muted-foreground', desc: msg`Insufficient HRV data for analysis` },
};
const DEFAULT_STATUS = STATUS_CONFIG.normal;

const TREND_LABELS: Record<string, { symbol: string; label: MessageDescriptor; class: string }> = {
  stable: { symbol: '\u2192', label: msg`Stable`, class: 'text-muted-foreground' },
  improving: { symbol: '\u2191', label: msg`Improving`, class: 'text-primary' },
  declining: { symbol: '\u2193', label: msg`Declining`, class: 'text-destructive' },
};

const RHR_LABELS: Record<string, { label: MessageDescriptor; class: string }> = {
  stable: { label: msg`Normal`, class: 'text-muted-foreground' },
  elevated: { label: msg`Elevated`, class: 'text-destructive' },
  low: { label: msg`Low`, class: 'text-primary' },
};

function formatLatestDate(dateStr: string, locale: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'short', day: 'numeric',
  });
}

export default function RecoveryPanel({ recovery, theoryMeta, analysis }: Props) {
  const { tsbZones } = useScience();
  const { i18n, t } = useLingui();
  const tsbZone = tsbZoneFromConfig(recovery.tsb, tsbZones);

  const headerTitle = theoryMeta
    ? `${t`Recovery`} \u00b7 ${theoryMeta.name}`
    : t`Recovery`;

  const status: RecoveryStatus = analysis?.status ?? 'normal';
  const statusCfg = STATUS_CONFIG[status] ?? DEFAULT_STATUS;
  const hrv = analysis?.hrv;
  const recoveryUnavailable = status === 'insufficient_data';
  const trendCfg = hrv ? (TREND_LABELS[hrv.trend] ?? TREND_LABELS.stable) : null;
  const isStale = analysis?.is_stale === true;
  const latestDate = analysis?.latest_date;
  const { locale } = useLocale();
  const latestDateLabel = latestDate ? formatLatestDate(latestDate, locale) : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {headerTitle}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isStale && latestDateLabel && (
          <div className="rounded-lg border border-dashed border-accent-amber/40 bg-accent-amber/5 p-3 mb-3">
            <p className="text-xs text-accent-amber">
              <Trans>
                Today's recovery hasn't synced yet. Showing the latest reading from {latestDateLabel}.
              </Trans>
            </p>
          </div>
        )}

        {/* Status — categorical output from Kiviniemi/Plews protocols */}
        <div className="rounded-xl bg-muted p-4 mb-3">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <Trans>Recovery Status</Trans>
            </p>
            <Badge className={`text-[10px] ${statusCfg.badgeBg} border-0`}>
              {i18n._(statusCfg.label)}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">{i18n._(statusCfg.desc)}</p>
        </div>

        {recoveryUnavailable && (
          <div className="rounded-lg border border-border bg-card p-3">
            <p className="text-sm text-muted-foreground">
              <Trans>Recovery requires HRV data from a compatible device (for example Oura Ring or an HRV-capable chest strap). Connect one to enable recovery status and suggestions.</Trans>
            </p>
          </div>
        )}

        {/* HRV Analysis — Plews protocol */}
        {!recoveryUnavailable && hrv && (
          <div className="mb-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              <Trans>HRV Analysis</Trans>
              <span className="text-muted-foreground/50 font-normal ml-1">(ln RMSSD)</span>
            </p>
            <div className="grid grid-cols-3 gap-2">
              {/* Today's value (or latest available, if today not synced) */}
              <div className={`rounded-lg bg-muted p-3 ${isStale ? 'opacity-70' : ''}`}>
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">
                  {isStale && latestDateLabel ? latestDateLabel : <Trans>Today</Trans>}
                </p>
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
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1"><Trans>Baseline</Trans></p>
                <span className="text-lg font-bold font-data text-foreground">
                  {hrv.baseline_mean_ln.toFixed(2)}
                </span>
                <span className="text-[9px] text-muted-foreground ml-1">
                  {'\u00b1'}{hrv.baseline_sd_ln.toFixed(2)}
                </span>
              </div>
              {/* 7-day trend */}
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1"><Trans>7d Trend</Trans></p>
                {trendCfg && (
                  <div className="flex items-baseline gap-1">
                    <span className={`text-lg font-bold ${trendCfg.class}`}>{trendCfg.symbol}</span>
                    <span className={`text-xs font-semibold ${trendCfg.class}`}>{i18n._(trendCfg.label)}</span>
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
                  <span className="text-[9px] text-accent-amber"><Trans>High variability</Trans></span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Informational signals — not part of the HRV model */}
        {!recoveryUnavailable && (
          <>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              <Trans>Other Signals</Trans>
            </p>
            <div className="grid grid-cols-3 gap-2 mb-3">
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">
                  <Trans>Sleep</Trans>
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
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">
                  RHR
                </p>
                <div className="flex items-baseline gap-1">
                  <span className="text-lg font-bold font-data text-foreground">
                    {analysis?.resting_hr != null ? Math.round(analysis.resting_hr) : '--'}
                  </span>
                  {analysis?.resting_hr != null && (
                    <span className="text-[9px] text-muted-foreground">bpm</span>
                  )}
                </div>
                {analysis?.rhr_trend && RHR_LABELS[analysis.rhr_trend] && (
                  <span className={`text-[9px] ${RHR_LABELS[analysis.rhr_trend].class}`}>
                    {i18n._(RHR_LABELS[analysis.rhr_trend].label)}
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
              text={t`Recovery status uses ln(RMSSD) compared to your personal baseline. 'Fatigued' = below baseline mean minus 1 SD (Kiviniemi et al, 2007 threshold). 'Fresh' = above baseline mean plus 0.5 SD (Plews et al, 2012 smallest worthwhile change). The 7-day trend and CV are monitored per Plews — declining trend or CV above 10% signals autonomic disturbance. Sleep, RHR, and TSB are shown as informational context when HRV is available.`}
              sourceUrl="https://link.springer.com/article/10.1007/s00421-012-2354-4"
              sourceLabel="Plews et al (2012)"
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}
