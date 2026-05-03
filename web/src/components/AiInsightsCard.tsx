import { useState, type ReactNode } from 'react';
import { useApi } from '@/hooks/useApi';
import type { AiInsight, AiInsightFinding } from '@/types/api';
import { msg } from '@lingui/core/macro';
import { Trans, Plural, useLingui } from '@lingui/react/macro';
import { useLocale } from '@/contexts/LocaleContext';
import { linkifyScienceTerms } from '@/lib/science-links';

/**
 * Deterministic "Praxys Coach" content rendered when no LLM insight
 * row exists for this slot. Lets the receipt remain the single
 * narrative-interpretation surface across pages — the user always sees
 * Praxys Coach, with AI content when it's there and rule-based content
 * otherwise. Without it, AiInsightsCard returns null when the LLM is
 * silent (legacy behavior).
 */
export interface CoachFallback {
  /** Lead sentence shown in the receipt body. Accepts ReactNode so
   *  callers can embed `<strong>` highlights for numbers (Goal does
   *  this — "<strong>14</strong> days to race day…"). */
  headline: ReactNode;
  summary?: string;
  findings?: AiInsightFinding[];
  recommendations?: string[];
  /** Stamp shown in the cobalt banner where AI insights show timeAgo
   *  (e.g. "6wk" lookback for a weekly diagnosis). Optional. */
  stamp?: string;
}

interface Props {
  /**
   * The insight slot to fetch (e.g. "daily_brief", "race_forecast").
   * Maps 1:1 to the same Praxys plugin skill name with underscores
   * converted to hyphens — drives the embedded "Open in Claude Code"
   * affordance at the bottom of the receipt.
   */
  insightType: string;
  /**
   * Optional theory attribution rendered in the muted receipt footer
   * (e.g. "HRV-Based Recovery · Banister PMC"). When provided, the
   * footer surfaces the science framework currently powering the
   * insight. Without it, the footer is suppressed entirely — keeps the
   * receipt clean when no attribution data is available at the call
   * site.
   */
  attribution?: string;
  /**
   * Deterministic content shown when the LLM insight slot is empty.
   * Without it, the component returns null on no AI insight (legacy
   * behavior used by callers that don't have a rule-based equivalent).
   */
  fallback?: CoachFallback;
}

const PLUGIN_URL = 'https://github.com/dddtc2005/praxys-coach-plugin#install';

// Mirrors Today.tsx's helper. Should be extracted to web/src/lib/format.ts
// when a third caller appears — see issue #236.
function timeAgo(isoDate: string, locale: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const rtf = new Intl.RelativeTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { style: 'short' });
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return rtf.format(-mins, 'minute');
  const hours = Math.floor(mins / 60);
  if (hours < 24) return rtf.format(-hours, 'hour');
  const days = Math.floor(hours / 24);
  return rtf.format(-days, 'day');
}

/**
 * Renders the Praxys Coach receipt — square-cornered, flat cobalt
 * banner, structured findings + recommendations, embedded Claude Code
 * skill hint. The single canonical narrative-interpretation surface
 * across pages.
 *
 * Content source ordering:
 *   1. LLM insight at /api/insights/{insightType} when present.
 *   2. Caller-provided `fallback` when the LLM slot is empty.
 *   3. null (component renders nothing) when neither is available.
 *
 * The receipt always carries the same brand banner regardless of
 * source — users see Praxys Coach whether the analysis was
 * AI-generated or computed from rule-based heuristics.
 */
export default function AiInsightsCard({ insightType, attribution, fallback }: Props) {
  const { data } = useApi<{ insight: AiInsight | null }>(`/api/insights/${insightType}`);
  const { locale } = useLocale();
  const { i18n } = useLingui();

  const [detailsOpen, setDetailsOpen] = useState(false);

  const insight = data?.insight;

  // Prefer the active-locale translation when present; fall back to
  // the top-level English fields (Issue #103 contract).
  const localized = insight && ((locale === 'zh' && insight.translations?.zh) || insight);

  // Resolve the actual content to render. AI takes precedence; fallback
  // fills in when AI is silent. If neither exists the surface stays
  // hidden — caller controls its own empty state.
  const content = localized
    ? {
        headline: localized.headline as ReactNode,
        summary: localized.summary,
        findings: localized.findings ?? insight!.findings ?? [],
        recommendations: localized.recommendations ?? insight!.recommendations ?? [],
        stamp: insight!.generated_at ? timeAgo(insight!.generated_at, locale) : undefined,
        isAi: true,
      }
    : fallback
      ? {
          headline: fallback.headline,
          summary: fallback.summary,
          findings: fallback.findings ?? [],
          recommendations: fallback.recommendations ?? [],
          stamp: fallback.stamp,
          isAi: false,
        }
      : null;

  if (!content) return null;

  // insightType -> plugin skill name mapping. The plugin's slash commands
  // use kebab-case (`/praxys:race-forecast`); insight rows in the DB use
  // snake_case (`race_forecast`). 1:1 transform.
  const skillName = insightType.replace(/_/g, '-');
  const hasDetails = content.findings.length > 0 || content.recommendations.length > 0;

  return (
    <aside className="coach-receipt" aria-label={i18n._(msg`Praxys Coach insight`)}>
      <div className="coach-banner">
        <span className="coach-mark"><Trans>Praxys Coach</Trans></span>
        {content.stamp && (
          <span className="coach-stamp font-data">{content.stamp}</span>
        )}
      </div>
      <div className="coach-body">
        <p className="coach-headline">{content.headline}</p>
        {content.summary && (
          <p className="coach-summary">{linkifyScienceTerms(content.summary)}</p>
        )}
        {hasDetails && (
          <button
            type="button"
            className="coach-toggle font-data"
            onClick={() => setDetailsOpen((v) => !v)}
            aria-expanded={detailsOpen}
          >
            <span className="coach-toggle-caret" aria-hidden="true">{detailsOpen ? '▾' : '▸'}</span>
            {detailsOpen ? (
              <Trans>Hide details</Trans>
            ) : (
              <span>
                {content.findings.length > 0 && (
                  <Plural
                    value={content.findings.length}
                    one="# finding"
                    other="# findings"
                  />
                )}
                {content.findings.length > 0 && content.recommendations.length > 0 && <Trans> · </Trans>}
                {content.recommendations.length > 0 && (
                  <Plural
                    value={content.recommendations.length}
                    one="# recommendation"
                    other="# recommendations"
                  />
                )}
              </span>
            )}
          </button>
        )}
        {detailsOpen && content.findings.length > 0 && (
          <>
            <p className="coach-label"><Trans>Findings</Trans></p>
            <ul className="coach-list">
              {content.findings.map((f, i) => (
                <li key={i} className={`coach-row coach-row-${f.type}`}>
                  <span className="coach-tag" aria-hidden="true">[{f.type === 'positive' ? '+' : f.type === 'warning' ? '!' : '·'}]</span>
                  <span className="coach-text">{linkifyScienceTerms(f.text)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {detailsOpen && content.recommendations.length > 0 && (
          <>
            {content.findings.length > 0 && <hr className="coach-rule" />}
            <p className="coach-label"><Trans>Recommendations</Trans></p>
            <ol className="coach-list">
              {content.recommendations.map((r, i) => (
                <li key={i} className="coach-row">
                  <span className="coach-tag coach-tag-rec" aria-hidden="true">→</span>
                  <span className="coach-text">{linkifyScienceTerms(r)}</span>
                </li>
              ))}
            </ol>
          </>
        )}
        {/* Claude Code plugin affordance — replaces the standalone
            CliHint card. The slash command is the data; the receipt is
            the carrier. */}
        <p className="coach-skill-hint">
          <Trans>
            Run{' '}
            <a
              href={PLUGIN_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="coach-skill-link"
            >
              /praxys:{skillName}
            </a>{' '}
            in Claude Code for deeper analysis
          </Trans>
        </p>
      </div>
      {attribution && <div className="coach-foot">{attribution}</div>}
    </aside>
  );
}
