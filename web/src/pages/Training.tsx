import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useApi } from '@/hooks/useApi';
import { useSettings } from '@/contexts/SettingsContext';
import type { TrainingResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import AiInsightsCard, { type CoachFallback } from '@/components/AiInsightsCard';
import ZoneAnalysisCard from '@/components/ZoneAnalysisCard';
import UpcomingPlanCard from '@/components/UpcomingPlanCard';
import FitnessFatigueChart from '@/components/charts/FitnessFatigueChart';
import ComplianceChart from '@/components/charts/ComplianceChart';
import DataHint from '@/components/DataHint';
import HeatAdaptationPanel from '@/components/HeatAdaptationPanel';
import { Trans, useLingui } from '@lingui/react/macro';

const DIAGNOSIS_CHART_KEY = 'praxys.diagnosis_chart';

interface DiagnosisChartOption {
  id: string;
  label: ReactNode;
  render: () => ReactNode;
}

/**
 * Segmented pill switcher inside the Diagnosis section. One slot,
 * one chart at a time. Active selection persisted to localStorage so
 * power users land on their preferred chart on every visit.
 *
 * Tab order matches the stat-strip order (TSB → Form, Distribution
 * match → Zone distribution, Load compliance → Compliance) so the
 * user reads a stat then looks at the corresponding chart below.
 *
 * Pill styling — solid primary fill on the active option, muted text
 * on the rest — was chosen over a subtle underline because the latter
 * read as static type at a glance and missed clicks. The pill is
 * unmistakably an interactive control.
 */
function DiagnosisChartSwitcher({ options }: { options: DiagnosisChartOption[] }) {
  const [active, setActive] = useState<string>(() => {
    if (typeof window === 'undefined') return options[0]?.id ?? '';
    const stored = window.localStorage.getItem(DIAGNOSIS_CHART_KEY);
    if (stored && options.some((o) => o.id === stored)) return stored;
    return options[0]?.id ?? '';
  });
  const current = options.find((o) => o.id === active) ?? options[0];
  if (!current) return null;

  return (
    <div>
      <div
        role="tablist"
        aria-label="Diagnosis chart"
        className="mb-6 grid w-full grid-cols-2 gap-1 rounded-xl bg-muted/60 p-1 text-[11px] font-medium sm:inline-flex sm:w-auto sm:items-center sm:rounded-full"
      >
        {options.map((opt) => {
          const isActive = opt.id === active;
          return (
            <button
              key={opt.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => {
                setActive(opt.id);
                if (typeof window !== 'undefined') {
                  window.localStorage.setItem(DIAGNOSIS_CHART_KEY, opt.id);
                }
              }}
              className={`min-w-0 rounded-lg px-3 py-2 text-center leading-tight transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:rounded-full sm:px-4 sm:py-1.5 ${
                isActive
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      <div>{current.render()}</div>
    </div>
  );
}

function TrainingSkeleton() {
  return (
    <div>
      <Skeleton className="h-3 w-20" />
      <div className="mt-3">
        <Skeleton className="mb-6 h-3 w-40" />
        <div className="mb-8 grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-3 lg:grid-cols-5 lg:gap-x-12">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i}>
              <Skeleton className="h-3 w-16 mb-2" />
              <Skeleton className="h-7 w-20 mb-1" />
              <Skeleton className="h-3 w-14" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-y-8 lg:grid-cols-[58fr_42fr] lg:gap-x-12">
          <div>
            <Skeleton className="h-3 w-32 mb-5" />
            <Skeleton className="h-96 w-full rounded-lg" />
          </div>
          <div className="lg:border-l lg:border-border lg:pl-12">
            <div className="coach-receipt">
              <div className="coach-banner">
                <Skeleton className="h-3 w-32 bg-card/30" />
                <Skeleton className="h-3 w-12 bg-card/30" />
              </div>
              <div className="coach-body">
                <Skeleton className="h-4 w-3/4 mb-3" />
                <Skeleton className="h-3 w-full mb-2" />
                <Skeleton className="h-3 w-5/6" />
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="mt-12 border-t border-border pt-8">
        <Skeleton className="h-3 w-32 mb-4" />
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
      target.scrollIntoView({ block: 'start' });
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

  // Theory attribution for the receipt foot — prefers the diagnosis's
  // own theory name, falls back to the load science-note label.
  // AiInsightsCard suppresses the foot entirely when undefined.
  const loadNote = data.science_notes?.load?.name;
  const theoryName = data.diagnosis.theory_name || loadNote;

  // Rule-based fallback for the Praxys Coach receipt — used when no
  // LLM `training_review` insight exists yet (no AZURE_AI_ENDPOINT,
  // or the post-sync runner hasn't populated the row). Lets the
  // narrative-led shape persist regardless of AI availability.
  const ruleFindings = data.diagnosis.diagnosis ?? [];
  const ruleSuggestions = data.diagnosis.suggestions ?? [];
  const distributionAvailable = data.diagnosis.data_meta.distribution_complete;


  const lead =
    ruleFindings.find((f) => f.type === 'warning') ??
    ruleFindings.find((f) => f.type === 'positive') ??
    ruleFindings[0];
  const fallback: CoachFallback = {
    headline: lead?.message ?? t`Weekly diagnosis ready.`,
    findings: ruleFindings.map((f) => ({ type: f.type, text: f.message })),
    recommendations: ruleSuggestions,
    stamp: `${data.diagnosis.lookback_weeks}wk`,
  };

  const {
    current_tsb: tsbCurrent,
    distribution_match_pct: distCompliance,
    load_compliance_pct: loadCompliance,
  } = data.summary;
  const loadTimeConstantDays = data.data_meta?.load_time_constant_days ?? 42;

  return (
    <div>
      {/* Page eyebrow — h1 doubles as eyebrow per Today.tsx convention. */}
      <h1 className="text-[10px] font-data uppercase tracking-[0.14em] text-muted-foreground">
        <Trans>Training</Trans>
      </h1>

      {/* ════════════════════════════════════════════════════════════════
          DIAGNOSIS · key numbers as a one-liner stat strip on top, then
          a 2-col below pairing the deep-dive chart (left) with the
          Coach receipt (right). The five stats answer five distinct
          training questions:
            TSB             — modeled load balance (CTL−ATL)
            Distribution    — similarity between observed and target zone mix
            Load compliance — completed-week actual/planned load ratio
            Volume          — amount of work (orphan, no chart pair)
            Heat adaptation — qualitative recent evidence; opens its
                              own evidence sheet because it has no chart tab
          The first three stats match chart-tab order (TSB → Form chart,
          Dist → Zones, Load → Compliance). Heat uses an explicit Evidence
          button so the other stat values remain passive and predictable.
          ════════════════════════════════════════════════════════════════ */}
      <section aria-label={t`Diagnosis`} className="mt-3">
        <div className="mb-6 flex items-baseline justify-between">
          <p className="text-[10px] font-data uppercase tracking-[0.18em] text-foreground font-semibold">
            <Trans>Diagnosis</Trans>
            <span className="text-muted-foreground font-normal tracking-[0.14em] ml-2">
              <Trans>· last {data.diagnosis.lookback_weeks} weeks</Trans>
            </span>
          </p>
        </div>

        {/* Stat strip — five peer metrics. Heat owns a clearly labeled
            evidence button rather than making the whole stat clickable. */}
        <div className="mb-8 grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-3 lg:grid-cols-5 lg:gap-x-12">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>TSB</Trans>
            </p>
            <p className="text-2xl font-semibold font-data text-foreground tabular-nums leading-none">
              {tsbCurrent != null
                ? `${tsbCurrent >= 0 ? '+' : ''}${tsbCurrent.toFixed(1)}`
                : '—'}
            </p>
            <p className="text-[11px] text-muted-foreground font-data mt-1">
              {tsbCurrent == null
                ? <Trans>modeled balance (CTL−ATL)</Trans>
                : tsbCurrent > 0
                  ? <Trans>long-term load above recent load</Trans>
                  : tsbCurrent < 0
                    ? <Trans>recent load above long-term load</Trans>
                    : <Trans>modeled loads balanced</Trans>}
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>Distribution match</Trans>
            </p>
            <p className="text-2xl font-semibold font-data text-foreground tabular-nums leading-none">
              {distCompliance != null ? distCompliance : '—'}
              {distCompliance != null && (
                <span className="text-base text-muted-foreground ml-0.5 font-normal">%</span>
              )}
            </p>
            <p className="text-[11px] text-muted-foreground font-data mt-1">
              {data.diagnosis.theory_name ? (
                <Trans>vs {data.diagnosis.theory_name}</Trans>
              ) : (
                <Trans>vs target zones</Trans>
              )}
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>Load compliance</Trans>
            </p>
            <p className="text-2xl font-semibold font-data text-foreground tabular-nums leading-none">
              {loadCompliance != null ? loadCompliance : '—'}
              {loadCompliance != null && (
                <span className="text-base text-muted-foreground ml-0.5 font-normal">%</span>
              )}
            </p>
            <p className="text-[11px] text-muted-foreground font-data mt-1">
              <Trans>actual vs planned, avg</Trans>
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>Volume</Trans>
            </p>
            <p className="text-2xl font-semibold font-data text-foreground tabular-nums leading-none">
              {data.diagnosis.volume?.weekly_avg_km != null
                ? data.diagnosis.volume.weekly_avg_km.toFixed(1)
                : '—'}
            </p>
            <p className="text-[11px] text-muted-foreground font-data mt-1">
              <Trans>km / week, {data.diagnosis.lookback_weeks}wk avg</Trans>
            </p>
          </div>
          <HeatAdaptationPanel status={data.heat_adaptation} />
        </div>

        {/* 2-col deep dive — chart switcher (left, 58%) + Coach receipt
            (right, 42%). Vertical hairline anchors the split. */}
        <div className="grid grid-cols-1 gap-y-8 lg:grid-cols-[58fr_42fr] lg:gap-x-12">
          <div className="lg:col-start-1 lg:row-start-1">
            <DiagnosisChartSwitcher
              options={[
                {
                  id: 'form',
                  label: <Trans>Long-term / Recent / Balance</Trans>,
                  render: () => {
                    const dataDays = data.data_meta?.data_days ?? 0;
                    const daysToPmc = Math.max(0, loadTimeConstantDays - dataDays);
                    return (
                      <DataHint
                        sufficient={data.data_meta?.pmc_sufficient ?? true}
                        message={t`Not enough data yet for stable load tracking`}
                        hint={t`The active load model uses a ${loadTimeConstantDays}-day long-term time constant. Need ${daysToPmc} more days of history.`}
                      >
                        <FitnessFatigueChart
                          data={data.fitness_fatigue}
                          scienceNote={data.science_notes?.load}
                        />
                      </DataHint>
                    );
                  },
                },
                ...(distributionAvailable && data.diagnosis.zone_ranges?.length > 0
                  ? [{
                      id: 'zones',
                      label: <Trans>Zone distribution</Trans>,
                      render: () => (
                        <ZoneAnalysisCard
                          distribution={data.diagnosis.distribution}
                          zoneRanges={data.diagnosis.zone_ranges}
                          theoryName={data.diagnosis.theory_name}
                          display={activeDisplay ?? undefined}
                          theoryDescription={data.science_notes?.zones?.description}
                        />
                      ),
                    }]
                  : []),
                {
                  id: 'compliance',
                  label: <Trans>Load compliance</Trans>,
                  render: () => {
                    const dataDays = data.data_meta?.data_days ?? 0;
                    const daysToCompare = Math.max(0, 14 - dataDays);
                    return (
                      <DataHint
                        sufficient={dataDays >= 14}
                        message={t`Not enough data yet for weekly load comparison`}
                        hint={t`Need 2 weeks of synced activity to compare planned vs actual. ${daysToCompare} more days to go.`}
                      >
                        <ComplianceChart data={data.weekly_review} loadLabel={activeDisplay?.load_label} />
                      </DataHint>
                    );
                  },
                },
              ]}
            />
          </div>
          <div className="lg:col-start-2 lg:row-start-1 lg:border-l lg:border-border lg:pl-12">
            <AiInsightsCard
              insightType="training_review"
              attribution={theoryName}
              fallback={fallback}
              onFeedbackStale={refetch}
            />
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════════
          PLAN · standalone section. Owns its own eyebrow + window pills,
          so the wrapper just provides vertical breathing room and a
          hairline separator from Diagnosis above.
          ════════════════════════════════════════════════════════════════ */}
      <div className="mt-12 border-t border-border pt-12">
        <UpcomingPlanCard />
      </div>
    </div>
  );
}
