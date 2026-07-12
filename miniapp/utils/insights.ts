/**
 * AI insight helpers for the miniapp.
 *
 * Web and miniapp both render durable training-review and race-forecast
 * insights. Use ``localizedInsight()`` for locale fallback and
 * ``fetchInsight()`` to load one of those durable types.
 *
 * Issue #103: top-level fields stay English; ``translations[locale]``
 * holds bilingual variants populated by the post-sync LLM runner.
 */
import type {
  AiInsight,
  AiInsightResponse,
  AiInsightTranslation,
  InsightFeedbackResponse,
  InsightFeedbackVote,
} from '../types/api';
import { apiPost, request } from './api-client';
import { t, tFmt } from './i18n';

export type InsightView = AiInsightTranslation;

const DATASET_HASH_RE = /^[0-9a-f]{64}$/;

/** Return the feedback version and prior vote safe to display for an insight. */
export function insightFeedbackState(
  insight: AiInsight | null,
): { datasetHash: string; vote: InsightFeedbackVote | '' } {
  const datasetHash = insight?.meta.dataset_hash;
  if (
    !insight
    || insight.feedback_allowed === false
    || typeof datasetHash !== 'string'
    || !DATASET_HASH_RE.test(datasetHash)
  ) {
    return { datasetHash: '', vote: '' };
  }

  const feedback = insight.meta.feedback;
  const vote = feedback?.dataset_hash === datasetHash
    && (feedback.vote === 'up' || feedback.vote === 'down')
    ? feedback.vote
    : '';
  return { datasetHash, vote };
}

/**
 * Pick the current-locale view of an insight, falling back to the
 * top-level English fields. Safe on partially-populated rows (legacy
 * inserts written before #103, generator failures that left
 * ``translations`` empty).
 */
export function localizedInsight(
  insight: AiInsight,
  locale: 'en' | 'zh',
): InsightView {
  const translated = insight.translations?.[locale];
  if (translated) return translated;
  return {
    headline: insight.headline,
    summary: insight.summary,
    findings: insight.findings ?? [],
    recommendations: insight.recommendations ?? [],
  };
}

/**
 * Fetch a specific insight from the backend. Returns ``null`` when the
 * row doesn't exist (matches the route's "no row → ``insight: null``"
 * shape).
 */
export async function fetchInsight(
  insightType: 'training_review' | 'race_forecast',
): Promise<AiInsight | null> {
  const resp = await request<AiInsightResponse>(
    `/api/insights/${insightType}`,
  );
  return resp.insight ?? null;
}

/** Submit one vote for the exact generated insight version shown to the user. */
export async function submitInsightFeedback(
  insightType: string,
  datasetHash: string,
  vote: InsightFeedbackVote,
  comment: string | null,
): Promise<InsightFeedbackResponse> {
  return apiPost<InsightFeedbackResponse>(
    `/api/insights/${insightType}/feedback`,
    { vote, dataset_hash: datasetHash, comment },
  );
}

/**
 * Render the Coach Receipt's progressive-disclosure toggle label.
 * Matches web's `AiInsightsCard` semantics:
 *   - expanded (`detailsOpen: true`)  → "Hide details"
 *   - collapsed + both fields present  → "{N} findings · {M} recommendations"
 *   - collapsed + findings only        → "{N} findings"
 *   - collapsed + recommendations only → "{M} recommendations"
 *
 * Web uses lingui ICU plural blocks (`# findings`); mini's `tFmt`
 * is positional only, so the noun stays plural at count=1 — minor
 * grammar imperfection vs. correctness, accepted because the count
 * itself already reads as the salient signal.
 *
 * Returns an empty string when there's nothing to disclose; callers
 * gate the toggle button on that.
 */
export function coachToggleLabel(
  findingCount: number,
  recommendationCount: number,
  detailsOpen: boolean,
): string {
  if (findingCount + recommendationCount === 0) return '';
  if (detailsOpen) return t('Hide details');
  if (findingCount > 0 && recommendationCount > 0) {
    return tFmt(
      '{0} findings · {1} recommendations',
      findingCount,
      recommendationCount,
    );
  }
  if (findingCount > 0) return tFmt('{0} findings', findingCount);
  return tFmt('{0} recommendations', recommendationCount);
}
