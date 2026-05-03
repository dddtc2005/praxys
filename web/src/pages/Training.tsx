import { useState, type ReactNode } from 'react';
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
import { msg } from '@lingui/core/macro';
import { Trans, useLingui } from '@lingui/react/macro';
import { tDisplay } from '@/lib/display-labels';

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
        className="inline-flex items-center gap-1 mb-6 rounded-full bg-muted/60 p-1 text-[11px] font-medium"
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
              className={`rounded-full px-4 py-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
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
        <Skeleton className="h-3 w-40 mb-7" />
        <div className="flex flex-wrap gap-x-12 gap-y-6 mb-8">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i}>
              <Skeleton className="h-3 w-16 mb-2" />
              <Skeleton className="h-7 w-20 mb-1" />
              <Skeleton className="h-3 w-14" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-y-8 lg:grid-cols-[58fr_42fr] lg:gap-x-10">
          <div>
            <Skeleton className="h-3 w-32 mb-5" />
            <Skeleton className="h-96 w-full rounded-lg" />
          </div>
          <div className="lg:border-l lg:border-border lg:pl-10">
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
  const { data, loading, error, refetch } = useApi<TrainingResponse>('/api/training');
  const { display } = useSettings();
  const { t, i18n } = useLingui();

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

  // Zone-distribution deviations folded into Coach findings + a
  // derived recommendation. Previously these lived as a standalone
  // Alert under the zone table; now they're owned by the receipt —
  // single source of interpretation across pages.
  const deviations = (data.diagnosis.distribution ?? [])
    .filter((d) => d.target_pct != null && Math.abs(d.actual_pct - d.target_pct!) > 5)
    .map((d) => {
      const diff = d.actual_pct - d.target_pct!;
      return {
        name: d.name,
        actual: d.actual_pct,
        target: d.target_pct!,
        diff,
        absDiff: Math.abs(diff),
      };
    });
  const distributionFindings = deviations.map((d) => ({
    type: 'warning' as const,
    text: t`${tDisplay(d.name, i18n)}: ${d.actual}% (${d.absDiff}pp ${d.diff > 0 ? t`above` : t`below`} ${d.target}% target)`,
  }));
  const worstDeviation = deviations.slice().sort((a, b) => b.absDiff - a.absDiff)[0];
  const distributionRec = worstDeviation
    ? worstDeviation.diff > 0
      ? i18n._(
          msg`Most over-target: ${tDisplay(worstDeviation.name, i18n)} at ${worstDeviation.actual}% (target ${worstDeviation.target}%). Shift 1-2 sessions next week toward an under-target zone.`,
        )
      : i18n._(
          msg`Most under-target: ${tDisplay(worstDeviation.name, i18n)} at ${worstDeviation.actual}% (target ${worstDeviation.target}%). Add 1-2 sessions in this zone next week.`,
        )
    : null;
  const allFindings = [
    ...ruleFindings.map((f) => ({ type: f.type, text: f.message })),
    ...distributionFindings,
  ];
  const allRecommendations = [
    ...ruleSuggestions,
    ...(distributionRec ? [distributionRec] : []),
  ];
  const lead =
    ruleFindings.find((f) => f.type === 'warning') ??
    ruleFindings.find((f) => f.type === 'positive') ??
    ruleFindings[0];
  const fallback: CoachFallback = {
    headline: lead?.message ?? i18n._(msg`Weekly diagnosis ready.`),
    findings: allFindings,
    recommendations: allRecommendations,
    stamp: `${data.diagnosis.lookback_weeks}wk`,
  };

  // Distribution-compliance score — 100 minus half the sum of absolute
  // deviations from target. Equivalent to a Bray-Curtis similarity
  // over the zone composition: 100% = identical, 0% = no overlap.
  // Skipped when no targets exist.
  const dist = data.diagnosis.distribution ?? [];
  const distWithTarget = dist.filter((z) => z.target_pct != null);
  const distCompliance = distWithTarget.length > 0
    ? Math.max(
        0,
        Math.round(
          100 -
            distWithTarget.reduce(
              (acc, z) => acc + Math.abs(z.actual_pct - (z.target_pct ?? 0)),
              0,
            ) / 2,
        ),
      )
    : null;

  // Load compliance — mean of weekly (actual / planned) over weeks
  // where a plan target existed.
  const wr = data.weekly_review;
  const loadRatios = (wr?.planned_load ?? [])
    .map((p, i) => {
      const a = wr?.actual_load?.[i] ?? 0;
      return p > 0 ? (a / p) * 100 : null;
    })
    .filter((r): r is number => r != null);
  const loadCompliance = loadRatios.length > 0
    ? Math.round(loadRatios.reduce((a, b) => a + b, 0) / loadRatios.length)
    : null;

  // Current TSB — last value in the fitness/fatigue series.
  const tsbSeries = data.fitness_fatigue?.tsb ?? [];
  const tsbCurrent = tsbSeries.length > 0 ? tsbSeries[tsbSeries.length - 1] : null;

  // Tone helpers — explicit threshold buckets per stat.
  const distTone =
    distCompliance == null
      ? 'muted'
      : distCompliance >= 85
        ? 'primary'
        : distCompliance >= 70
          ? 'amber'
          : 'destructive';
  const loadTone =
    loadCompliance == null
      ? 'muted'
      : loadCompliance >= 80 && loadCompliance <= 120
        ? 'primary'
        : loadCompliance < 80
          ? 'amber'
          : 'destructive';
  const tsbTone =
    tsbCurrent == null
      ? 'muted'
      : tsbCurrent >= 5
        ? 'primary'
        : tsbCurrent >= -10
          ? 'muted'
          : 'destructive';
  const toneClass = (tone: string) =>
    tone === 'primary'
      ? 'text-primary'
      : tone === 'amber'
        ? 'text-accent-amber'
        : tone === 'destructive'
          ? 'text-destructive'
          : 'text-foreground';

  return (
    <div>
      {/* Page eyebrow — h1 doubles as eyebrow per Today.tsx convention. */}
      <h1 className="text-[10px] font-data uppercase tracking-[0.14em] text-muted-foreground">
        <Trans>Training</Trans>
      </h1>

      {/* ════════════════════════════════════════════════════════════════
          DIAGNOSIS · key numbers as a one-liner stat strip on top, then
          a 2-col below pairing the deep-dive chart (left) with the
          Coach receipt (right). The four stats answer four distinct
          training questions:
            TSB             — current form (CTL−ATL)
            Distribution    — how well your zone mix matches the target
            Load compliance — how well you executed the planned load
            Volume          — amount of work (orphan, no chart pair)
          Stat order matches chart-tab order (TSB → Form chart, Dist →
          Zones, Load → Compliance) so the user reads stat → glances
          at the corresponding chart in the switcher.
          ════════════════════════════════════════════════════════════════ */}
      <section aria-label={t`Diagnosis`} className="mt-3">
        <div className="flex items-baseline justify-between mb-7">
          <p className="text-[10px] font-data uppercase tracking-[0.18em] text-foreground font-semibold">
            <Trans>Diagnosis</Trans>
            <span className="text-muted-foreground font-normal tracking-[0.14em] ml-2">
              <Trans>· last {data.diagnosis.lookback_weeks} weeks</Trans>
            </span>
          </p>
        </div>

        {/* Stat strip — full-width one-liner. Wraps to 2x2 at narrow
            viewports. */}
        <div className="grid grid-cols-2 gap-x-10 gap-y-6 sm:flex sm:flex-wrap sm:gap-x-14 lg:gap-x-20 mb-8">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>TSB</Trans>
            </p>
            <p className={`text-2xl font-semibold font-data tabular-nums leading-none ${toneClass(tsbTone)}`}>
              {tsbCurrent != null
                ? `${tsbCurrent >= 0 ? '+' : ''}${tsbCurrent.toFixed(1)}`
                : '—'}
            </p>
            <p className="text-[11px] text-muted-foreground font-data mt-1">
              {tsbCurrent == null
                ? <Trans>form (CTL−ATL)</Trans>
                : tsbCurrent >= 5
                  ? <Trans>fresh, primed</Trans>
                  : tsbCurrent >= 0
                    ? <Trans>balanced</Trans>
                    : tsbCurrent >= -10
                      ? <Trans>productive load</Trans>
                      : <Trans>fatigue accumulating</Trans>}
            </p>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
              <Trans>Distribution match</Trans>
            </p>
            <p className={`text-2xl font-semibold font-data tabular-nums leading-none ${toneClass(distTone)}`}>
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
            <p className={`text-2xl font-semibold font-data tabular-nums leading-none ${toneClass(loadTone)}`}>
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
        </div>

        {/* 2-col deep dive — chart switcher (left, 58%) + Coach receipt
            (right, 42%). Vertical hairline anchors the split. */}
        <div className="grid grid-cols-1 gap-y-8 lg:grid-cols-[58fr_42fr] lg:gap-x-10">
          <div className="lg:col-start-1 lg:row-start-1">
            <DiagnosisChartSwitcher
              options={[
                {
                  id: 'form',
                  label: <Trans>Fitness / Fatigue / Form</Trans>,
                  render: () => {
                    // PMC needs ~42 days of data before CTL stabilises;
                    // until then the lines mostly trace recency bias and
                    // mislead more than they help. Show the countdown so
                    // the user knows when the chart will become useful.
                    const dataDays = data.data_meta?.data_days ?? 0;
                    const daysToPmc = Math.max(0, 42 - dataDays);
                    return (
                      <DataHint
                        sufficient={data.data_meta?.pmc_sufficient ?? true}
                        message={t`Not enough data yet for accurate fitness tracking`}
                        hint={t`Banister PMC stabilises after about 42 days of activity. Need ${daysToPmc} more days.`}
                      >
                        <FitnessFatigueChart
                          data={data.fitness_fatigue}
                          scienceNote={data.science_notes?.load}
                        />
                      </DataHint>
                    );
                  },
                },
                ...(data.diagnosis.zone_ranges?.length > 0
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
          <div className="lg:col-start-2 lg:row-start-1 lg:border-l lg:border-border lg:pl-10">
            <AiInsightsCard
              insightType="training_review"
              attribution={theoryName}
              fallback={fallback}
            />
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════════
          PLAN · standalone section. Owns its own eyebrow + window pills,
          so the wrapper just provides vertical breathing room and a
          hairline separator from Diagnosis above.
          ════════════════════════════════════════════════════════════════ */}
      <div className="mt-12 border-t border-border pt-10">
        <UpcomingPlanCard />
      </div>
    </div>
  );
}
