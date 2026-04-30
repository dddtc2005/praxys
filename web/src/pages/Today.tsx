import { lazy, Suspense } from 'react';
import { useApi } from '@/hooks/useApi';
import type { TodayResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { AlertTriangle } from 'lucide-react';
import SignalHero from '@/components/SignalHero';
import RecoveryPanel from '@/components/RecoveryPanel';
import WorkoutCard from '@/components/WorkoutCard';

// Lazy-loaded: recharts (397 KB) is only needed for this chart.
// Wrapping in Suspense lets SignalHero + RecoveryPanel + WorkoutCard
// render before recharts parses, which is the visible first paint.
const FormSparkline = lazy(() => import('@/components/charts/FormSparkline'));
import LastActivityCard from '@/components/LastActivityCard';
import WeeklyLoadMini from '@/components/WeeklyLoadMini';
import DataHint from '@/components/DataHint';
import CliHint from '@/components/CliHint';
import AiInsightsCard from '@/components/AiInsightsCard';
import { Trans, useLingui } from '@lingui/react/macro';
import { useLocale } from '@/contexts/LocaleContext';

function TodaySkeleton() {
  return (
    <div className="space-y-6">
      <div>
        <Skeleton className="h-8 w-24" />
        <Skeleton className="h-4 w-48 mt-2" />
      </div>
      <Skeleton className="h-60 w-full rounded-2xl" />
      <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
        <Skeleton className="h-48 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
      <Skeleton className="h-32 w-full rounded-2xl" />
    </div>
  );
}

export default function Today() {
  const { data, loading, error, refetch } = useApi<TodayResponse>('/api/today');
  const { locale } = useLocale();
  const { t } = useLingui();

  const now = new Date();
  const dateStr = now.toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  if (loading) return <TodaySkeleton />;

  if (error) {
    return (
      <Alert variant="destructive" className="my-12">
        <AlertTitle><Trans>Failed to load</Trans></AlertTitle>
        <AlertDescription className="flex items-center justify-between">
          <span>{error}</span>
          <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (!data) return null;

  const { signal, tsb_sparkline, warnings } = data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground"><Trans>Today</Trans></h1>
        <p className="text-sm text-muted-foreground mt-1">{dateStr}</p>
      </div>

      {/* Signal Hero — full width */}
      <SignalHero recommendation={signal.recommendation} reason={signal.reason} />

      {/* Praxys Coach: today's brief — sits between the rule-based signal
          hero and the recovery/workout grid so the LLM commentary is the
          first interpretive layer the athlete sees. Renders nothing when
          no insight row exists (LLM disabled, generation cap hit). */}
      <AiInsightsCard insightType="daily_brief" />

      {/* Two-column grid: Recovery + Workout */}
      <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
        <RecoveryPanel recovery={signal.recovery} theoryMeta={data.recovery_theory} analysis={data.recovery_analysis} />
        <WorkoutCard plan={signal.plan} alternatives={signal.alternatives} upcoming={data.upcoming} />
      </div>

      {/* Form sparkline — full width. Lazy-loaded so recharts parses after
          the hero content above is already visible. */}
      <Suspense fallback={<Skeleton className="h-48 w-full rounded-2xl" />}>
        <DataHint
          sufficient={data.data_meta?.pmc_sufficient ?? true}
          message={t`Not enough data for accurate form tracking`}
          hint={t`Sync at least 6 weeks of activity data to see your training form trend.`}
        >
          <FormSparkline data={tsb_sparkline} scienceNote={data.science_notes?.load} />
        </DataHint>
      </Suspense>

      {/* Context row: Last Activity + Weekly Load */}
      {(data.last_activity || data.week_load) && (
        <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
          {data.last_activity && <LastActivityCard activity={data.last_activity} />}
          {data.week_load && <WeeklyLoadMini weekLoad={data.week_load} />}
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <Trans>Warnings</Trans>
          </h3>
          {warnings.map((w, i) => (
            <Alert key={i} className="border-accent-amber/30 bg-accent-amber/5 text-accent-amber [&>svg]:text-accent-amber">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{w}</AlertDescription>
            </Alert>
          ))}
        </div>
      )}

      <CliHint
        skill="daily-brief"
        title={t`AI Daily Brief`}
        description={t`Get personalized training recommendations, recovery assessment, and today's training signal with the Claude Code plugin.`}
      />
    </div>
  );
}
