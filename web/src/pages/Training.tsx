import { useApi } from '@/hooks/useApi';
import { useSettings } from '@/contexts/SettingsContext';
import type { TrainingResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import DiagnosisCard from '@/components/DiagnosisCard';
import UpcomingPlanCard from '@/components/UpcomingPlanCard';
import FitnessFatigueChart from '@/components/charts/FitnessFatigueChart';
import CpTrendChart from '@/components/charts/CpTrendChart';
import ComplianceChart from '@/components/charts/ComplianceChart';
import SleepPerfChart from '@/components/charts/SleepPerfChart';

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
  const { data, loading, error } = useApi<TrainingResponse>('/api/training');
  const { display } = useSettings();

  const activeDisplay = data?.display ?? display;

  if (loading) return <TrainingSkeleton />;

  if (error) {
    return (
      <Alert variant="destructive" className="my-12">
        <AlertTitle>Failed to load training data</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
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

      {/* Upcoming plan schedule */}
      <div className="mb-6">
        <UpcomingPlanCard />
      </div>

      {/* Charts grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="lg:col-span-2">
          <FitnessFatigueChart data={data.fitness_fatigue} />
        </div>
        <div className="lg:col-span-2">
          <CpTrendChart data={data.cp_trend} label={activeDisplay?.trend_label} unit={activeDisplay?.threshold_unit} metricName={activeDisplay?.threshold_abbrev} />
        </div>
        <ComplianceChart data={data.weekly_review} loadLabel={activeDisplay?.load_label} />
        <SleepPerfChart data={data.sleep_perf} />
      </div>

      {/* Workout Flags */}
      {data.workout_flags.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              What Worked / What Didn't
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {data.workout_flags.map((flag, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                      flag.type === 'good'
                        ? 'bg-primary/20 text-primary'
                        : 'bg-destructive/20 text-destructive'
                    }`}
                  >
                    {flag.type === 'good' ? '+' : '\u2013'}
                  </span>
                  <div className="min-w-0">
                    <span className="text-xs font-data text-muted-foreground">{flag.date}</span>
                    <p className="text-sm text-muted-foreground">{flag.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
