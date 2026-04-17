import { useApi } from '@/hooks/useApi';
import { useSettings } from '@/contexts/SettingsContext';
import type { TrainingResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
// Card imports kept for future use
// import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import DiagnosisCard from '@/components/DiagnosisCard';
import ZoneAnalysisCard from '@/components/ZoneAnalysisCard';
import UpcomingPlanCard from '@/components/UpcomingPlanCard';
import FitnessFatigueChart from '@/components/charts/FitnessFatigueChart';
import CpTrendChart from '@/components/charts/CpTrendChart';
import ComplianceChart from '@/components/charts/ComplianceChart';
import SleepPerfChart from '@/components/charts/SleepPerfChart';
import DataHint from '@/components/DataHint';

function TrainingSkeleton() {
  return (
    <div>
      <div className="mb-8">
        <Skeleton className="h-8 w-44" />
        <Skeleton className="h-4 w-28 mt-2" />
      </div>
      <Skeleton className="h-64 rounded-2xl mb-6" />
      <Skeleton className="h-48 rounded-2xl mb-6" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <Skeleton className="h-96 rounded-2xl lg:col-span-2" />
        <Skeleton className="h-80 rounded-2xl lg:col-span-2" />
        <Skeleton className="h-80 rounded-2xl" />
        <Skeleton className="h-80 rounded-2xl" />
      </div>
    </div>
  );
}

export default function Training() {
  const { data, loading, error, refetch } = useApi<TrainingResponse>('/api/training');
  const { display } = useSettings();

  const activeDisplay = data?.display ?? display;

  if (loading) return <TrainingSkeleton />;

  if (error) {
    return (
      <Alert variant="destructive" className="my-12">
        <AlertTitle>Failed to load training data</AlertTitle>
        <AlertDescription className="flex items-center justify-between">
          <span>{error}</span>
          <Button variant="outline" size="sm" onClick={() => refetch()}>Retry</Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (!data) return null;

  return (
    <div>
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">Training Insights</h1>
        <p className="text-sm text-muted-foreground mt-1">Weekly Review</p>
      </div>

      {/* Diagnosis card — full width */}
      <div className="mb-6">
        <DiagnosisCard diagnosis={data.diagnosis} display={activeDisplay ?? undefined} />
      </div>

      {/* Zone analysis card */}
      {data.diagnosis.zone_ranges?.length > 0 && (
        <div className="mb-6">
          <ZoneAnalysisCard
            distribution={data.diagnosis.distribution}
            zoneRanges={data.diagnosis.zone_ranges}
            theoryName={data.diagnosis.theory_name}
            display={activeDisplay ?? undefined}
          />
        </div>
      )}

      {/* Upcoming plan schedule */}
      <div className="mb-6">
        <UpcomingPlanCard />
      </div>

      {/* Charts grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="lg:col-span-2">
          <DataHint
            sufficient={data.data_meta?.pmc_sufficient ?? true}
            message="Not enough data for accurate fitness tracking"
            hint="Sync at least 6 weeks of activity data to see meaningful fitness, fatigue, and form curves."
          >
            <FitnessFatigueChart data={data.fitness_fatigue} scienceNote={data.science_notes?.load} />
          </DataHint>
        </div>
        <div className="lg:col-span-2">
          <DataHint
            sufficient={data.data_meta?.cp_trend_sufficient ?? true}
            message="Not enough data to show CP trend"
            hint="Need at least 3 activities with power data to plot a meaningful trend."
          >
            <CpTrendChart data={data.cp_trend} label={activeDisplay?.trend_label} unit={activeDisplay?.threshold_unit} metricName={activeDisplay?.threshold_abbrev} />
          </DataHint>
        </div>
        <DataHint
          sufficient={(data.data_meta?.data_days ?? 0) >= 14}
          message="Not enough data for weekly load comparison"
          hint="Sync at least 2 weeks of data to compare planned vs actual training load."
        >
          <ComplianceChart data={data.weekly_review} loadLabel={activeDisplay?.load_label} />
        </DataHint>
        <DataHint
          sufficient={!!(data.data_meta?.has_recovery && (data.sleep_perf?.length ?? 0) >= 2)}
          message="Not enough data to show sleep vs performance"
          hint="Connect a recovery source (like Oura Ring) and sync activities with power data."
        >
          <SleepPerfChart data={data.sleep_perf} />
        </DataHint>
      </div>

      {/* Workout Flags — removed, needs better analysis than avg power comparison */}
    </div>
  );
}
