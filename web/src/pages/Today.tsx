import { useApi } from '@/hooks/useApi';
import type { AiInsight, TodayResponse, TrainingSignal } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Trans } from '@lingui/react/macro';
import { useLocale } from '@/contexts/LocaleContext';
import { linkifyScienceTerms } from '@/lib/science-links';

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

const VERDICT_LABEL: Record<TrainingSignal['recommendation'], string> = {
  follow_plan: 'GO',
  easy: 'EASY',
  modify: 'MODIFY',
  reduce_intensity: 'REDUCE',
  rest: 'REST',
};

function verdictColorClass(rec: TrainingSignal['recommendation']): string {
  if (rec === 'follow_plan') return 'today-verdict-go';
  if (rec === 'rest') return 'today-verdict-rest';
  return '';
}

const TREND_ARROW = { stable: '→', improving: '↑', declining: '↓' } as const;

function formatPlan(plan: TrainingSignal['plan']): string | null {
  if (!plan?.workout_type) return null;
  const parts: string[] = [plan.workout_type];
  if (plan.distance_km != null) parts.push(`${plan.distance_km.toFixed(1)} km`);
  if (plan.duration_min != null) parts.push(`${plan.duration_min} min`);
  if (plan.power_min != null && plan.power_max != null) {
    parts.push(`${plan.power_min}–${plan.power_max} W`);
  }
  return parts.join(' · ');
}

export default function Today() {
  const { data, loading, error, refetch } = useApi<TodayResponse>('/api/today');
  // Same query key as AiInsightsCard, so React Query dedupes the fetch.
  const { data: briefData } = useApi<{ insight: AiInsight | null }>('/api/insights/daily_brief');
  const { locale } = useLocale();

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

  const { signal, recovery_analysis: ra } = data;
  const verdictText = VERDICT_LABEL[signal.recommendation] ?? signal.recommendation.toUpperCase();
  const verdictModifier = verdictColorClass(signal.recommendation);
  const insight = briefData?.insight ?? null;
  const localizedInsight =
    insight && locale === 'zh' && insight.translations?.zh ? insight.translations.zh : insight;

  const hrv = ra?.hrv ?? null;
  const trendArrow = hrv ? TREND_ARROW[hrv.trend] : '—';
  const trendCv = hrv != null ? `${(hrv.rolling_cv * 100).toFixed(1)}%` : '—';
  const sleepScore = ra?.sleep_score;
  const restingHr = ra?.resting_hr;
  const tsb = signal.recovery.tsb;
  const tsbDisplay = `${tsb >= 0 ? '+' : ''}${tsb.toFixed(1)}`;
  const tsbDescriptor = tsb > 10 ? 'strongly positive' : tsb > 0 ? 'positive' : tsb > -10 ? 'mild fatigue' : 'fatigued';
  const planText = formatPlan(signal.plan) ?? 'Rest day. No workout scheduled.';

  return (
    <div className="today-spread">
      <p className="today-eyebrow">Today · {dateStr}</p>
      <h1 className={`today-verdict ${verdictModifier}`.trim()}>{verdictText}</h1>
      <p className="today-rationale">{signal.reason}</p>

      {localizedInsight && (
        <aside className="today-gloss">
          <div className="today-gloss-eyebrow">
            <Trans>Praxys Coach</Trans>
            {localizedInsight.headline ? <> · {localizedInsight.headline}</> : null}
          </div>
          <p className="today-gloss-text">{linkifyScienceTerms(localizedInsight.summary ?? '')}</p>
        </aside>
      )}

      <div className="today-supporting">
        <div className="today-cell">
          <span className="today-cell-label">HRV (ln RMSSD)</span>
          <span className="today-cell-value">{hrv ? hrv.today_ln.toFixed(2) : '—'}</span>
          <span className="today-cell-sub">
            {hrv?.today_ms != null ? `${hrv.today_ms} ms · ` : ''}
            {hrv ? `vs ${hrv.baseline_mean_ln.toFixed(2)} baseline` : 'no data'}
          </span>
        </div>
        <div className="today-cell">
          <span className="today-cell-label">7d Trend</span>
          <span className="today-cell-value">{trendArrow}</span>
          <span className="today-cell-sub">{hrv ? `${hrv.trend} · CV ${trendCv}` : 'no data'}</span>
        </div>
        <div className="today-cell">
          <span className="today-cell-label">RHR</span>
          <span className="today-cell-value">{restingHr != null ? restingHr : '—'}</span>
          <span className="today-cell-sub">{restingHr != null ? `bpm · ${ra?.rhr_trend ?? 'normal'}` : 'no data'}</span>
        </div>
        <div className="today-cell">
          <span className="today-cell-label">Sleep</span>
          <span className="today-cell-value">{sleepScore != null ? sleepScore : '—'}</span>
          <span className="today-cell-sub">{sleepScore != null ? 'overnight score' : 'no data'}</span>
        </div>
        <div className="today-cell">
          <span className="today-cell-label">TSB</span>
          <span className={`today-cell-value ${tsb > 0 ? 'today-cell-value-positive' : ''}`.trim()}>{tsbDisplay}</span>
          <span className="today-cell-sub">{tsbDescriptor}</span>
        </div>
      </div>

      <div className="today-plan">
        <span className="today-plan-eyebrow">Planned · Today</span>
        <span className="today-plan-text">{planText}</span>
      </div>
    </div>
  );
}
