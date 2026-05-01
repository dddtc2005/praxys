import { useState } from 'react';
import { useApi } from '@/hooks/useApi';
import type { AiInsight } from '@/types/api';
import { msg } from '@lingui/core/macro';
import { Trans, Plural, useLingui } from '@lingui/react/macro';
import { useLocale } from '@/contexts/LocaleContext';
import { linkifyScienceTerms } from '@/lib/science-links';

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
}

const PLUGIN_URL = 'https://github.com/dddtc2005/praxys';

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
 * Renders an LLM-generated Praxys Coach insight as the canonical
 * coach-receipt component (square-cornered, flat cobalt banner,
 * structured findings + recommendations, embedded Claude Code skill
 * hint). Replaces the prior purple-bordered card pattern that has been
 * retired (see PR #245).
 *
 * Returns null when no insight row exists yet — the rule-based
 * fallback prose lives in the calling page (e.g. Today's signal.reason
 * suppressed under hasCoachBrief).
 */
export default function AiInsightsCard({ insightType, attribution }: Props) {
  const { data } = useApi<{ insight: AiInsight | null }>(`/api/insights/${insightType}`);
  const { locale } = useLocale();
  const { i18n } = useLingui();

  const [detailsOpen, setDetailsOpen] = useState(false);

  const insight = data?.insight;
  if (!insight) return null;

  // Prefer the active-locale translation when present; fall back to the
  // top-level English fields (Issue #103 contract).
  const localized = (locale === 'zh' && insight.translations?.zh) || insight;
  const headline = localized.headline;
  const summary = localized.summary;
  const findings = localized.findings ?? insight.findings ?? [];
  const recommendations = localized.recommendations ?? insight.recommendations ?? [];
  const hasDetails = findings.length > 0 || recommendations.length > 0;

  // insightType -> plugin skill name mapping. The plugin's slash commands
  // use kebab-case (`/praxys:race-forecast`); insight rows in the DB use
  // snake_case (`race_forecast`). 1:1 transform.
  const skillName = insightType.replace(/_/g, '-');

  return (
    <aside className="coach-receipt" aria-label={i18n._(msg`Praxys Coach insight`)}>
      <div className="coach-banner">
        <span className="coach-mark"><Trans>Praxys Coach</Trans></span>
        {insight.generated_at && (
          <span className="coach-stamp font-data">{timeAgo(insight.generated_at, locale)}</span>
        )}
      </div>
      <div className="coach-body">
        <p className="coach-headline">{headline}</p>
        {summary && (
          <p className="coach-summary">{linkifyScienceTerms(summary)}</p>
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
                {findings.length > 0 && (
                  <Plural
                    value={findings.length}
                    one="# finding"
                    other="# findings"
                  />
                )}
                {findings.length > 0 && recommendations.length > 0 && <Trans> · </Trans>}
                {recommendations.length > 0 && (
                  <Plural
                    value={recommendations.length}
                    one="# recommendation"
                    other="# recommendations"
                  />
                )}
              </span>
            )}
          </button>
        )}
        {detailsOpen && findings.length > 0 && (
          <>
            <p className="coach-label"><Trans>Findings</Trans></p>
            <ul className="coach-list">
              {findings.map((f, i) => (
                <li key={i} className={`coach-row coach-row-${f.type}`}>
                  <span className="coach-tag" aria-hidden="true">[{f.type === 'positive' ? '+' : f.type === 'warning' ? '!' : '·'}]</span>
                  <span className="coach-text">{linkifyScienceTerms(f.text)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {detailsOpen && recommendations.length > 0 && (
          <>
            {findings.length > 0 && <hr className="coach-rule" />}
            <p className="coach-label"><Trans>Recommendations</Trans></p>
            <ol className="coach-list">
              {recommendations.map((r, i) => (
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
