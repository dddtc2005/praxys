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
  fresh: { label: msg`Above reference band`, class: 'text-foreground', badgeBg: 'bg-muted text-foreground', desc: msg`HRV is above your Praxys reference band` },
  normal: { label: msg`Within reference band`, class: 'text-foreground', badgeBg: 'bg-muted text-muted-foreground', desc: msg`HRV is within your Praxys reference band` },
  fatigued: { label: msg`Below caution band`, class: 'text-accent-amber', badgeBg: 'bg-accent-amber/10 text-accent-amber', desc: msg`HRV is below your Praxys caution band` },
  insufficient_data: { label: msg`No current classification`, class: 'text-muted-foreground', badgeBg: 'bg-muted text-muted-foreground', desc: msg`Insufficient current HRV data for comparison` },
};
const DEFAULT_STATUS = STATUS_CONFIG.normal;

const TREND_LABELS: Record<string, { symbol: string; label: MessageDescriptor; class: string }> = {
  stable: { symbol: '\u2192', label: msg`Stable`, class: 'text-muted-foreground' },
  improving: { symbol: '\u2191', label: msg`Rising`, class: 'text-muted-foreground' },
  declining: { symbol: '\u2193', label: msg`Falling`, class: 'text-muted-foreground' },
};

const RHR_LABELS: Record<string, { label: MessageDescriptor; class: string }> = {
  stable: { label: msg`Near baseline`, class: 'text-muted-foreground' },
  elevated: { label: msg`Above baseline`, class: 'text-accent-amber' },
  low: { label: msg`Below baseline`, class: 'text-muted-foreground' },
};

function formatLatestDate(dateStr: string, locale: string): string {
  // Parse the ISO date-only string as a local calendar date. `new Date("YYYY-MM-DD")`
  // would be parsed as UTC midnight and shift backward in negative-offset locales
  // (e.g. en-US users see "Apr 24" for an ISO "2026-04-25").
  const [y, m, day] = dateStr.split('-').map(Number);
  if (!y || !m || !day) return dateStr;
  const d = new Date(y, m - 1, day);
  return d.toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'short', day: 'numeric',
  });
}

export default function RecoveryPanel({ recovery, theoryMeta, analysis }: Props) {
  const { tsbZones } = useScience();
  const { i18n, t } = useLingui();
  const tsbZone = recovery.tsb == null
    ? null
    : tsbZoneFromConfig(recovery.tsb, tsbZones);

  const headerTitle = theoryMeta
    ? `${t`Recovery`} \u00b7 ${theoryMeta.name}`
    : t`Recovery`;

  const status: RecoveryStatus = analysis?.status ?? 'normal';
  const statusCfg = STATUS_CONFIG[status] ?? DEFAULT_STATUS;
  const hrv = analysis?.hrv;
  const cvThreshold = theoryMeta?.params.cv_threshold ?? 10;
  const observationCount = theoryMeta?.params.rolling_days ?? 7;
  const sleepScore = analysis?.sleep_score ?? recovery.sleep_score;
  const readinessScore = analysis?.readiness_score ?? recovery.readiness;
  const recoveryUnavailable = status === 'insufficient_data';
  const trendCfg = hrv ? (TREND_LABELS[hrv.trend] ?? TREND_LABELS.stable) : null;
  const isStale = analysis?.is_stale === true;
  const latestDate = analysis?.latest_date;
  const { locale } = useLocale();
  const latestDateLabel = latestDate ? formatLatestDate(latestDate, locale) : null;
  const hrvDateLabel = analysis?.hrv_latest_date ? formatLatestDate(analysis.hrv_latest_date, locale) : null;
  const sleepDateLabel = analysis?.sleep_latest_date ? formatLatestDate(analysis.sleep_latest_date, locale) : null;
  const readinessDateLabel = analysis?.readiness_latest_date ? formatLatestDate(analysis.readiness_latest_date, locale) : null;
  const rhrDateLabel = analysis?.rhr_latest_date ? formatLatestDate(analysis.rhr_latest_date, locale) : null;

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

        {/* Status is a Praxys operational adaptation of the cited HRV research. */}
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
          <div className="rounded-lg border border-border bg-card p-3 mb-3">
            <p className="text-sm text-muted-foreground">
              {analysis?.classification_reason === 'zero_variance' ? (
                <Trans>Recent HRV observations have no measurable variation, so Praxys cannot form a reliable recovery band yet. Keep syncing to add natural variation.</Trans>
              ) : analysis?.classification_reason === 'insufficient_history' ? (
                <Trans>More historical HRV observations are needed before Praxys can form a personal recovery band. Keep syncing your device.</Trans>
              ) : analysis?.hrv_is_stale ? (
                <Trans>The latest HRV reading is too old for a same-day recovery classification. Sync your device to refresh it.</Trans>
              ) : (
                <Trans>Recovery requires current HRV data from a compatible device (for example Oura Ring or an HRV-capable chest strap). Connect or sync one to enable recovery status and suggestions.</Trans>
              )}
            </p>
          </div>
        )}

        {/* HRV Analysis — Plews protocol */}
        {hrv && (
          <div className="mb-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              <Trans>HRV Analysis</Trans>
              <span className="text-muted-foreground/50 font-normal ml-1">(ln RMSSD)</span>
            </p>
            <div className="grid grid-cols-3 gap-2">
              {/* Today's value (or latest available, if today not synced) */}
              <div className={`rounded-lg bg-muted p-3 ${analysis?.hrv_is_stale ? 'opacity-70' : ''}`}>
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">
                  {hrvDateLabel ?? <Trans>Today</Trans>}
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
              {/* Observation-count trend */}
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1"><Trans>{observationCount}-observation Trend</Trans></p>
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
                <span className={`text-xs font-data font-semibold ${hrv.rolling_cv > cvThreshold ? 'text-accent-amber' : 'text-muted-foreground'}`}>
                  {hrv.rolling_cv.toFixed(1)}%
                </span>
                {hrv.rolling_cv > cvThreshold && (
                  <span className="text-[9px] text-accent-amber"><Trans>High variability</Trans></span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Informational signals — displayed independently from HRV classification */}
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
          <Trans>Other Signals</Trans>
        </p>
        <div className="grid grid-cols-2 gap-2 mb-3 sm:grid-cols-4">
          <div className="rounded-lg bg-muted p-3">
            <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>Sleep</Trans>
            </p>
            <span className={`text-lg font-bold font-data ${sleepScore != null ? 'text-foreground' : 'text-muted-foreground'}`}>
              {sleepScore ?? '--'}
            </span>
            {sleepDateLabel && <span className="block text-[9px] text-muted-foreground mt-1">{sleepDateLabel}</span>}
          </div>
          <div className="rounded-lg bg-muted p-3">
            <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>Readiness</Trans>
            </p>
            <span className={`text-lg font-bold font-data ${readinessScore != null ? 'text-foreground' : 'text-muted-foreground'}`}>
              {readinessScore ?? '--'}
            </span>
            {readinessDateLabel && <span className="block text-[9px] text-muted-foreground mt-1">{readinessDateLabel}</span>}
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
            {rhrDateLabel && <span className="block text-[9px] text-muted-foreground mt-1">{rhrDateLabel}</span>}
          </div>
          <div className="rounded-lg bg-muted p-3">
            <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1" style={{ color: tsbZone?.color }}>
              TSB
            </p>
            <span className="text-lg font-bold font-data" style={{ color: tsbZone?.color }}>
              {recovery.tsb == null ? '—' : recovery.tsb.toFixed(1)}
            </span>
          </div>
        </div>

        <ScienceNote
          text={t`Praxys adapts individualized HRV-guided training and ln(RMSSD) trend monitoring into operational reference bands. The exact reference-band and caution-band cutoffs are product guardrails, not thresholds validated by the cited studies. CV above ${cvThreshold}% is also a coaching caution flag, not a diagnosis. Sleep, readiness, RHR, and TSB remain separate informational context.`}
          sources={[
            { url: 'https://doi.org/10.1007/s00421-012-2354-4', label: 'Plews et al (2012)' },
            { url: 'https://doi.org/10.1007/s00421-007-0552-2', label: 'Kiviniemi et al (2007)' },
          ]}
        />
      </CardContent>
    </Card>
  );
}
