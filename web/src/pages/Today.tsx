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
  reduce_intensity: 'CAUTION',
  rest: 'REST',
};

const VERDICT_SUBTITLE: Record<TrainingSignal['recommendation'], string> = {
  follow_plan: 'Follow plan',
  easy: 'Go easy',
  modify: 'Adjust workout',
  reduce_intensity: 'Reduce intensity',
  rest: 'Recovery day',
};

type SignalTone = 'green' | 'amber' | 'red';

const VERDICT_TONE: Record<TrainingSignal['recommendation'], SignalTone> = {
  follow_plan: 'green',
  easy: 'amber',
  modify: 'amber',
  reduce_intensity: 'amber',
  rest: 'red',
};

const TONE_CLASSES: Record<SignalTone, { text: string; bg: string; ring: string; shadow: string }> = {
  green: {
    text: 'text-primary',
    bg: 'bg-primary',
    ring: 'ring-accent-green/30',
    shadow: 'shadow-[0_0_40px_rgba(0,255,135,0.3)]',
  },
  amber: {
    text: 'text-accent-amber',
    bg: 'bg-accent-amber',
    ring: 'ring-accent-amber/30',
    shadow: 'shadow-[0_0_40px_rgba(245,158,11,0.3)]',
  },
  red: {
    text: 'text-destructive',
    bg: 'bg-destructive',
    ring: 'ring-accent-red/30',
    shadow: 'shadow-[0_0_40px_rgba(239,68,68,0.3)]',
  },
};

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
  const verdictSubtitle = VERDICT_SUBTITLE[signal.recommendation] ?? signal.recommendation;
  const tone = TONE_CLASSES[VERDICT_TONE[signal.recommendation] ?? 'amber'];
  const insight = briefData?.insight ?? null;
  const localizedInsight =
    insight && locale === 'zh' && insight.translations?.zh ? insight.translations.zh : insight;
  // When the LLM Coach narrative is available, suppress the rule-based reason —
  // it covers the same ground in a more generic voice. Rule-based is the fallback.
  const hasCoachBrief = localizedInsight != null;

  const hrv = ra?.hrv ?? null;
  const trendArrow = hrv ? TREND_ARROW[hrv.trend] : '—';
  const trendCv = hrv != null ? `${hrv.rolling_cv.toFixed(1)}%` : '—';
  const sleepScore = ra?.sleep_score;
  const restingHr = ra?.resting_hr;
  const rhrDisplay = restingHr != null ? Math.round(restingHr) : '—';
  const tsb = signal.recovery.tsb;
  const tsbDisplay = `${tsb >= 0 ? '+' : ''}${tsb.toFixed(1)}`;
  const tsbDescriptor = tsb > 10 ? 'strongly positive' : tsb > 0 ? 'positive' : tsb > -10 ? 'mild fatigue' : 'fatigued';
  const planText = formatPlan(signal.plan) ?? 'Rest day. No workout scheduled.';

  return (
    <div className="today-spread">
      <p className="today-eyebrow">Today · {dateStr}</p>
      <div className="today-verdict">
        <div
          className={`relative flex h-32 w-32 items-center justify-center rounded-full ring-4 ${tone.ring} ${tone.shadow}`}
        >
          <div className={`absolute inset-0 rounded-full ${tone.bg} opacity-10 animate-pulse`} />
          <span className={`relative text-3xl font-bold font-data tracking-wider ${tone.text}`}>
            {verdictText}
          </span>
        </div>
        <p className={`text-lg font-semibold ${tone.text}`}>{verdictSubtitle}</p>
      </div>
      {!hasCoachBrief && <p className="today-rationale">{signal.reason}</p>}

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
          <span className="today-cell-value">{rhrDisplay}</span>
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
