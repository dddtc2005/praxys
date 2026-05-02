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
