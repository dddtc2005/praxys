import type { DiagnosisData, DiagnosisFinding, DisplayConfig } from '@/types/api';
import DistributionBar from '@/components/DistributionBar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Trans, useLingui } from '@lingui/react/macro';
import { tDisplay } from '@/lib/display-labels';

interface Props {
  diagnosis: DiagnosisData;
  display?: DisplayConfig;
}

function FindingIcon({ type }: { type: DiagnosisFinding['type'] }) {
  if (type === 'positive') {
    return <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-bold text-primary">+</span>;
  }
  if (type === 'warning') {
    return <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-amber/20 text-xs font-bold text-accent-amber">!</span>;
  }
  return <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted-foreground/20 text-xs font-bold text-muted-foreground">&ndash;</span>;
}

export default function DiagnosisCard({ diagnosis, display }: Props) {
  const { volume, interval_power, distribution, diagnosis: findings, suggestions } = diagnosis;
  const { i18n } = useLingui();

  const intensityLabel = tDisplay(display?.intensity_metric ?? 'Power', i18n);
  const unit = display?.threshold_unit ?? 'W';
  const distArr = Array.isArray(distribution) ? distribution : [];
  const topZoneName = tDisplay(distArr.length > 0 ? distArr[distArr.length - 1].name : 'VO2max', i18n);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Trans>Training Diagnosis</Trans></CardTitle>
      </CardHeader>
      <CardContent>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <div>
          <p className="text-xs text-muted-foreground mb-1"><Trans>Weekly Volume</Trans></p>
          <p className="text-xl font-bold font-data text-foreground">
            {volume?.weekly_avg_km != null ? volume.weekly_avg_km.toFixed(1) : '—'}<span className="text-sm text-muted-foreground ml-1">km</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1"><Trans>Peak Interval {intensityLabel}</Trans></p>
          <p className="text-xl font-bold font-data text-foreground">
            {interval_power.max != null ? interval_power.max : '—'}<span className="text-sm text-muted-foreground ml-1">{unit}</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1"><Trans>Avg Work {intensityLabel}</Trans></p>
          <p className="text-xl font-bold font-data text-foreground">
            {interval_power.avg_work != null ? interval_power.avg_work : '—'}<span className="text-sm text-muted-foreground ml-1">{unit}</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1"><Trans>{topZoneName} / Quality</Trans></p>
          <p className="text-xl font-bold font-data text-foreground">
            <span className="text-destructive">{interval_power?.supra_cp_sessions ?? '—'}</span>
            <span className="text-muted-foreground mx-1">/</span>
            {interval_power?.total_quality_sessions ?? '—'}
          </p>
        </div>
      </div>

      {/* Distribution bar */}
      <div className="mb-6">
        <DistributionBar distribution={distArr} />
      </div>

      {/* Findings */}
      <div className="space-y-2.5 mb-5">
        {findings.map((finding, i) => (
          <div key={i} className="flex items-start gap-2.5">
            <FindingIcon type={finding.type} />
            <p className="text-sm text-muted-foreground leading-relaxed">{finding.message}</p>
          </div>
        ))}
      </div>

      {/* Suggestions */}
      {suggestions.length > 0 && (
        <>
          <div className="border-t border-border mb-4" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3"><Trans>Suggestions</Trans></h3>
          <ul className="space-y-1.5">
            {suggestions.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                {s}
              </li>
            ))}
          </ul>
        </>
      )}
      </CardContent>
    </Card>
  );
}
