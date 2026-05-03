/**
 * AI insight helpers for the miniapp.
 *
 * The web app surfaces ``AiInsight`` rows via ``AiInsightsCard``; the
 * miniapp does not render those cards yet (deliberate parity gap — see
 * ``docs/dev/architecture.md`` "LLM-backed insights"). When that
 * rendering is added, use ``localizedInsight()`` to pick the active-locale
 * block with English fallback, and ``fetchInsight()`` to load by type.
 *
 * Issue #103: top-level fields stay English; ``translations[locale]``
 * holds bilingual variants populated by the post-sync LLM runner.
 */
import type { AiInsight, AiInsightTranslation } from '../types/api';
import { request } from './api-client';
import { t, tFmt } from './i18n';

export type InsightView = AiInsightTranslation;

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
  insightType: 'daily_brief' | 'training_review' | 'race_forecast',
): Promise<AiInsight | null> {
  const resp = await request<{ insight: AiInsight | null }>(
    `/api/insights/${insightType}`,
  );
  return resp.insight ?? null;
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
