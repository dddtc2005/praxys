import { useApi } from '@/hooks/useApi';
import { useSettings } from '@/contexts/SettingsContext';
import type { TrainingResponse } from '@/types/api';
import DiagnosisCard from '@/components/DiagnosisCard';
import UpcomingPlanCard from '@/components/UpcomingPlanCard';
import FitnessFatigueChart from '@/components/charts/FitnessFatigueChart';
import CpTrendChart from '@/components/charts/CpTrendChart';
import ComplianceChart from '@/components/charts/ComplianceChart';
import SleepPerfChart from '@/components/charts/SleepPerfChart';

export default function Training() {
  const { data, loading, error } = useApi<TrainingResponse>('/api/training');
  const { display } = useSettings();

  // Use display from API response (most current), fall back to settings context
  const activeDisplay = data?.display ?? display;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl bg-card p-6 text-center">
        <p className="text-destructive font-semibold mb-2">Failed to load training data</p>
        <p className="text-sm text-muted-foreground">{error}</p>
      </div>
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
        {/* Fitness/Fatigue — full width */}
        <div className="lg:col-span-2">
          <FitnessFatigueChart data={data.fitness_fatigue} />
        </div>

        {/* Threshold Trend — full width */}
        <div className="lg:col-span-2">
          <CpTrendChart data={data.cp_trend} label={activeDisplay?.trend_label} unit={activeDisplay?.threshold_unit} metricName={activeDisplay?.threshold_abbrev} />
        </div>

        {/* Compliance — left */}
        <ComplianceChart data={data.weekly_review} loadLabel={activeDisplay?.load_label} />

        {/* Sleep vs Perf — right */}
        <SleepPerfChart data={data.sleep_perf} />
      </div>

      {/* Workout Flags */}
      {data.workout_flags.length > 0 && (
        <div className="rounded-2xl bg-card p-5 sm:p-6">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
            What Worked / What Didn't
          </h3>
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
        </div>
      )}
    </div>
  );
}
