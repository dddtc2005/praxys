import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Trans, useLingui } from '@lingui/react/macro';
import { ChevronRight } from 'lucide-react';
import { useLocation } from 'react-router-dom';

import AiInsightsCard, { type CoachFallback } from '@/components/AiInsightsCard';
import DataHint from '@/components/DataHint';
import {
  default as HeatAdaptationDetail,
  HeatAdaptationMetricContext,
  HeatAdaptationMetricValue,
  HeatAdaptationSheetDescription,
} from '@/components/HeatAdaptationPanel';
import MetricDetailSheet, { type MetricSheetSize } from '@/components/MetricDetailSheet';
import UpcomingPlanCard from '@/components/UpcomingPlanCard';
import ZoneAnalysisCard from '@/components/ZoneAnalysisCard';
import ComplianceChart from '@/components/charts/ComplianceChart';
import FitnessFatigueChart from '@/components/charts/FitnessFatigueChart';
import WeeklyVolumeChart from '@/components/charts/WeeklyVolumeChart';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useSettings } from '@/contexts/SettingsContext';
import { useApi } from '@/hooks/useApi';
import type { TrainingResponse } from '@/types/api';

type TrainingMetricId = 'tsb' | 'distribution' | 'load' | 'volume' | 'heat';

interface TrainingMetric {
  id: TrainingMetricId;
  anchorId?: string;
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  context: ReactNode;
  sheetTitle: ReactNode;
  sheetDescription: ReactNode;
  sheetSize: MetricSheetSize;
  detail: ReactNode;
}

function PeerMetricList({
  metrics,
  onOpen,
}: {
  metrics: TrainingMetric[];
  onOpen: (metric: TrainingMetricId) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card/35 divide-y divide-border">
      {metrics.map((metric) => (
        <button
          key={metric.id}
          id={metric.anchorId}
          type="button"
          aria-haspopup="dialog"
          onClick={() => onOpen(metric.id)}
          className="group grid min-h-20 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-4 py-3.5 text-left transition-colors hover:bg-muted/45 active:bg-muted/65 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:px-5"
        >
          <span className="min-w-0">
            <span className="block text-xs font-semibold text-foreground">
              {metric.label}
            </span>
            <span className="mt-1 block text-[11px] leading-snug text-muted-foreground">
              {metric.context}
            </span>
          </span>

          <span className="flex min-w-[5.5rem] items-baseline justify-end gap-1 text-right sm:min-w-[7.5rem]">
            <span className="font-data text-xl font-semibold tabular-nums text-foreground">
              {metric.value}
            </span>
            {metric.unit && (
              <span className="text-xs text-muted-foreground">{metric.unit}</span>
            )}
          </span>

          <span className="col-span-2 inline-flex items-center justify-end gap-1 text-[11px] font-medium text-accent-cobalt sm:col-span-1 sm:min-w-[4.5rem]">
            <Trans>Details</Trans>
            <ChevronRight
              className="size-3.5 transition-transform duration-200 group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </span>
        </button>
      ))}
    </div>
  );
}

function TrainingSkeleton() {
  return (
    <div>
      <Skeleton className="h-3 w-20" />
      <div className="mt-3">
        <Skeleton className="mb-6 h-3 w-40" />
        <div className="grid grid-cols-1 items-start gap-y-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(24rem,1.1fr)] lg:gap-x-10">
          <div>
            <Skeleton className="mb-2 h-4 w-24" />
            <Skeleton className="mb-4 h-3 w-64 max-w-full" />
            <div className="overflow-hidden rounded-xl border border-border">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="flex min-h-20 items-center justify-between gap-6 border-b border-border px-5 last:border-b-0">
                  <div>
                    <Skeleton className="mb-2 h-3 w-28" />
                    <Skeleton className="h-3 w-40 max-w-full" />
                  </div>
                  <Skeleton className="h-6 w-20" />
                </div>
              ))}
            </div>
          </div>
          <div className="coach-receipt">
            <div className="coach-banner">
              <Skeleton className="h-3 w-32 bg-card/30" />
              <Skeleton className="h-3 w-12 bg-card/30" />
            </div>
            <div className="coach-body">
              <Skeleton className="mb-3 h-4 w-3/4" />
              <Skeleton className="mb-2 h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
            </div>
          </div>
        </div>
      </div>
      <div className="mt-14">
        <Skeleton className="mb-4 h-3 w-32" />
        <Skeleton className="h-40 rounded-lg" />
      </div>
    </div>
  );
}

export default function Training() {
  const { data, loading, error, refetch } = useApi<TrainingResponse>(
    '/api/training',
    {
      refetchOnMount: 'always',
      refetchOnWindowFocus: 'always',
    },
  );
  const { display } = useSettings();
  const { t } = useLingui();
  const location = useLocation();
  const heatAnchorScrollKey = useRef<string | null>(null);
  const [activeMetric, setActiveMetric] = useState<TrainingMetricId | null>(null);

  useEffect(() => {
    if (
      loading
      || !data
      || location.hash !== '#heat-adaptation'
      || heatAnchorScrollKey.current === location.key
    ) {
      return undefined;
    }
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById('heat-adaptation');
      if (!target) return;
      target.scrollIntoView({ block: 'center' });
      setActiveMetric('heat');
      heatAnchorScrollKey.current = location.key;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [data, loading, location.hash, location.key]);

  const activeDisplay = data?.display ?? display;

  if (loading) return <TrainingSkeleton />;

  if (error) {
    return (
      <Alert variant="destructive" className="my-12">
        <AlertTitle><Trans>Failed to load training data</Trans></AlertTitle>
        <AlertDescription className="flex items-center justify-between">
          <span>{error}</span>
          <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (!data) return null;

  const loadNote = data.science_notes?.load?.name;
  const theoryName = data.diagnosis.theory_name || loadNote;
  const ruleFindings = data.diagnosis.diagnosis ?? [];
  const ruleSuggestions = data.diagnosis.suggestions ?? [];
  const distributionAvailable = data.diagnosis.data_meta.distribution_complete;
  const lead =
    ruleFindings.find((finding) => finding.type === 'warning')
    ?? ruleFindings.find((finding) => finding.type === 'positive')
    ?? ruleFindings[0];
  const fallback: CoachFallback = {
    headline: lead?.message ?? t`Weekly diagnosis ready.`,
    findings: ruleFindings.map((finding) => ({ type: finding.type, text: finding.message })),
    recommendations: ruleSuggestions,
    stamp: `${data.diagnosis.lookback_weeks}wk`,
  };

  const {
    current_tsb: tsbCurrent,
    distribution_match_pct: distributionMatch,
    load_compliance_pct: loadCompliance,
  } = data.summary;
  const dataDays = data.data_meta?.data_days ?? 0;
  const loadTimeConstantDays = data.data_meta?.load_time_constant_days ?? 42;
  const daysToPmc = Math.max(0, loadTimeConstantDays - dataDays);
  const daysToCompare = Math.max(0, 14 - dataDays);
  const pmcAvailable = data.data_meta?.pmc_sufficient ?? true;
  const distributionDetailAvailable =
    distributionAvailable && data.diagnosis.zone_ranges.length > 0;
  const loadDetailAvailable = dataDays >= 14;
  const volumeWeeks = data.diagnosis.volume.weeks;
  const volumeDistances = data.diagnosis.volume.weekly_km;
  const volumeSummaryAvailable = volumeWeeks === undefined
    ? data.diagnosis.volume.weekly_avg_km > 0
    : volumeWeeks.length > 0;
  const volumeSeriesPending = volumeWeeks === undefined || volumeDistances === undefined;
  const volumeSeriesAvailable = (
    volumeWeeks !== undefined
    && volumeWeeks.length > 0
    && volumeWeeks.length === (volumeDistances?.length ?? -1)
  );

  const metrics: TrainingMetric[] = [
    {
      id: 'tsb',
      label: <Trans>TSB</Trans>,
      value: tsbCurrent != null
        ? `${tsbCurrent >= 0 ? '+' : ''}${tsbCurrent.toFixed(1)}`
        : '—',
      context: tsbCurrent == null
        ? <Trans>modeled balance (CTL−ATL)</Trans>
        : tsbCurrent > 0
          ? <Trans>long-term load above recent load</Trans>
          : tsbCurrent < 0
            ? <Trans>recent load above long-term load</Trans>
            : <Trans>modeled loads balanced</Trans>,
      sheetTitle: <Trans>Load balance</Trans>,
      sheetDescription: (
        <Trans>Long-term load, recent load, and their modeled balance over time.</Trans>
      ),
      sheetSize: pmcAvailable ? 'wide' : 'standard',
      detail: (
        <DataHint
          sufficient={pmcAvailable}
          message={t`Not enough data yet for stable load tracking`}
          hint={t`The active load model uses a ${loadTimeConstantDays}-day long-term time constant. Need ${daysToPmc} more days of history.`}
        >
          <FitnessFatigueChart
            data={data.fitness_fatigue}
            scienceNote={data.science_notes?.load}
          />
        </DataHint>
      ),
    },
    {
      id: 'distribution',
      label: <Trans>Distribution match</Trans>,
      value: distributionMatch != null ? distributionMatch : '—',
      unit: distributionMatch != null ? '%' : undefined,
      context: data.diagnosis.theory_name
        ? <Trans>vs {data.diagnosis.theory_name}</Trans>
        : <Trans>vs target zones</Trans>,
      sheetTitle: <Trans>Zone distribution</Trans>,
      sheetDescription: (
        <Trans>Observed time in each intensity zone compared with the selected training theory.</Trans>
      ),
      sheetSize: distributionDetailAvailable ? 'wide' : 'standard',
      detail: (
        <DataHint
          sufficient={distributionDetailAvailable}
          message={t`Not enough complete intensity data for zone comparison`}
          hint={t`Sync split or sample data with enough duration coverage to compare against the selected theory.`}
        >
          <ZoneAnalysisCard
            distribution={data.diagnosis.distribution}
            zoneRanges={data.diagnosis.zone_ranges}
            theoryName={data.diagnosis.theory_name}
            display={activeDisplay ?? undefined}
            theoryDescription={data.science_notes?.zones?.description}
          />
        </DataHint>
      ),
    },
    {
      id: 'load',
      label: <Trans>Load compliance</Trans>,
      value: loadCompliance != null ? loadCompliance : '—',
      unit: loadCompliance != null ? '%' : undefined,
      context: <Trans>actual vs planned, avg</Trans>,
      sheetTitle: <Trans>Load compliance</Trans>,
      sheetDescription: (
        <Trans>Actual and planned weekly load across the recent training window.</Trans>
      ),
      sheetSize: loadDetailAvailable ? 'wide' : 'standard',
      detail: (
        <DataHint
          sufficient={loadDetailAvailable}
          message={t`Not enough data yet for weekly load comparison`}
          hint={t`Need 2 weeks of synced activity to compare planned vs actual. ${daysToCompare} more days to go.`}
        >
          <ComplianceChart data={data.weekly_review} loadLabel={activeDisplay?.load_label} />
        </DataHint>
      ),
    },
    {
      id: 'volume',
      label: <Trans>Volume</Trans>,
      value: volumeSummaryAvailable ? data.diagnosis.volume.weekly_avg_km.toFixed(1) : '—',
      unit: volumeSummaryAvailable ? <Trans>km/wk</Trans> : undefined,
      context: <Trans>{data.diagnosis.lookback_weeks}-week average</Trans>,
      sheetTitle: <Trans>Weekly volume</Trans>,
      sheetDescription: (
        <Trans>
          Recorded distance in non-overlapping seven-day buckets, including weeks with no recorded distance.
        </Trans>
      ),
      sheetSize: volumeSeriesAvailable ? 'wide' : 'standard',
      detail: (
        <DataHint
          sufficient={volumeSeriesAvailable}
          message={
            volumeSeriesPending
              ? t`Weekly chart temporarily unavailable`
              : t`No weekly distance history yet`
          }
          hint={
            volumeSeriesPending
              ? t`The weekly history will appear after the data service update completes.`
              : t`Sync recent activities to populate the weekly distance series.`
          }
        >
          <WeeklyVolumeChart volume={data.diagnosis.volume} />
        </DataHint>
      ),
    },
    {
      id: 'heat',
      anchorId: 'heat-adaptation',
      label: <Trans>Heat adaptation</Trans>,
      value: <HeatAdaptationMetricValue status={data.heat_adaptation} />,
      context: <HeatAdaptationMetricContext status={data.heat_adaptation} />,
      sheetTitle: <Trans>Heat adaptation</Trans>,
      sheetDescription: <HeatAdaptationSheetDescription status={data.heat_adaptation} />,
      sheetSize: 'standard',
      detail: <HeatAdaptationDetail status={data.heat_adaptation} />,
    },
  ];
  const activeDefinition = metrics.find((metric) => metric.id === activeMetric) ?? null;

  return (
    <div>
      <h1 className="text-[11px] font-data uppercase tracking-[0.14em] text-muted-foreground">
        <Trans>Training</Trans>
      </h1>

      <section aria-label={t`Diagnosis`} className="mt-3">
        <p className="mb-6 text-[11px] font-data uppercase tracking-[0.18em] text-foreground font-semibold">
          <Trans>Diagnosis</Trans>
          <span className="ml-2 font-normal tracking-[0.14em] text-muted-foreground">
            <Trans>· last {data.diagnosis.lookback_weeks} weeks</Trans>
          </span>
        </p>

        <div className="grid grid-cols-1 items-start gap-y-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(24rem,1.1fr)] lg:gap-x-10">
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              <Trans>Peer metrics</Trans>
            </h2>
            <p className="mb-4 mt-1 text-xs leading-relaxed text-muted-foreground">
              <Trans>Select a metric to inspect its chart or evidence.</Trans>
            </p>
            <PeerMetricList metrics={metrics} onOpen={setActiveMetric} />
          </div>

          <AiInsightsCard
            insightType="training_review"
            attribution={theoryName}
            fallback={fallback}
            onFeedbackStale={refetch}
          />
        </div>
      </section>

      <div className="mt-14">
        <UpcomingPlanCard />
      </div>

      <MetricDetailSheet
        open={activeDefinition != null}
        onOpenChange={(open) => {
          if (!open) setActiveMetric(null);
        }}
        size={activeDefinition?.sheetSize ?? 'standard'}
        title={activeDefinition?.sheetTitle ?? ''}
        description={activeDefinition?.sheetDescription ?? ''}
      >
        {activeDefinition?.detail}
      </MetricDetailSheet>
    </div>
  );
}
