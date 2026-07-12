import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Check, ThumbsDown, ThumbsUp } from 'lucide-react';
import { API_BASE, getAuthHeaders, useApi } from '@/hooks/useApi';
import type {
  AiInsightResponse,
  AiInsightFinding,
  InsightFeedbackResponse,
  InsightFeedbackVote,
} from '@/types/api';
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
  /** The insight slot to fetch (e.g. "daily_brief", "race_forecast"). */
  insightType: string;
  /** Optional theory attribution rendered in the muted receipt footer. */
  attribution?: string;
  /** Deterministic content shown when the LLM insight slot is empty. */
  fallback?: CoachFallback;
  /** Called the first time the user expands the receipt's reasoning details. */
  onDetailsOpen?: () => void;
  /** Refresh the page dataset when the displayed insight version is stale. */
  onFeedbackStale?: () => void | Promise<void>;
}

const PLUGIN_URL = 'https://github.com/praxys-run/praxys-coach-plugin#install';

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

/** Render the canonical Praxys Coach receipt with AI-only feedback controls. */
export default function AiInsightsCard({
  insightType,
  attribution,
  fallback,
  onDetailsOpen,
  onFeedbackStale,
}: Props) {
  const { data, refetch } = useApi<AiInsightResponse>(`/api/insights/${insightType}`);
  const { locale } = useLocale();
  const { i18n } = useLingui();

  const [detailsOpen, setDetailsOpen] = useState(false);
  const [feedbackVote, setFeedbackVote] = useState<InsightFeedbackVote | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackSending, setFeedbackSending] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [feedbackStale, setFeedbackStale] = useState(false);
  const [feedbackError, setFeedbackError] = useState('');

  const insight = data?.insight;
  const rawDatasetHash = insight?.meta.dataset_hash;
  const datasetHash = insight?.feedback_allowed !== false
    && typeof rawDatasetHash === 'string'
    && /^[0-9a-f]{64}$/.test(rawDatasetHash)
    ? rawDatasetHash
    : null;
  const persistedFeedback = insight?.meta.feedback;
  const feedbackIdentityRef = useRef('');
  feedbackIdentityRef.current = `${insightType}:${datasetHash ?? ''}`;

  useEffect(() => {
    const matchesCurrent = datasetHash
      && persistedFeedback?.dataset_hash === datasetHash
      && (persistedFeedback.vote === 'up' || persistedFeedback.vote === 'down');
    setFeedbackVote(matchesCurrent ? persistedFeedback.vote : null);
    setFeedbackSent(Boolean(matchesCurrent));
    setFeedbackStale(false);
    setFeedbackSending(false);
    setFeedbackOpen(false);
    setFeedbackComment('');
    setFeedbackError('');
  }, [datasetHash, persistedFeedback?.dataset_hash, persistedFeedback?.vote]);

  // Prefer the active-locale translation when present; fall back to
  // the top-level English fields (Issue #103 contract).
  const localized = insight && ((locale === 'zh' && insight.translations?.zh) || insight);

  // Resolve the actual content to render. AI takes precedence; fallback
  // fills in when AI is silent. If neither exists the surface stays hidden.
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

  const canCollectFeedback = Boolean(content?.isAi && datasetHash);

  const cancelFeedback = () => {
    if (feedbackSending) return;
    setFeedbackVote(null);
    setFeedbackOpen(false);
    setFeedbackComment('');
    setFeedbackError('');
  };

  const selectFeedback = (vote: InsightFeedbackVote) => {
    if (feedbackSent || feedbackSending || feedbackStale) return;
    if (feedbackVote === vote && feedbackOpen) {
      cancelFeedback();
      return;
    }
    setFeedbackVote(vote);
    setFeedbackOpen(true);
    setFeedbackError('');
  };

  const sendFeedback = async () => {
    if (!feedbackVote || !datasetHash || feedbackStale) return;
    const requestIdentity = feedbackIdentityRef.current;
    const requestIsCurrent = () => feedbackIdentityRef.current === requestIdentity;
    setFeedbackSending(true);
    setFeedbackError('');
    try {
      const response = await fetch(`${API_BASE}/api/insights/${insightType}/feedback`, {
        method: 'POST',
        headers: {
          ...(getAuthHeaders() as Record<string, string>),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          vote: feedbackVote,
          dataset_hash: datasetHash,
          comment: feedbackComment.trim() || null,
        }),
      });
      if (!requestIsCurrent()) return;
      if (!response.ok) {
        const errorBody = await response.json().catch(() => null) as { detail?: unknown } | null;
        if (!requestIsCurrent()) return;
        if (
          response.status === 409
          && (
            errorBody?.detail === 'INSIGHT_FEEDBACK_STALE'
            || errorBody?.detail === 'INSIGHT_FEEDBACK_UNVERSIONED'
          )
        ) {
          setFeedbackStale(true);
          setFeedbackError(i18n._(msg`This insight changed. Refresh the page before sending feedback.`));
          const refreshes: Array<Promise<unknown>> = [refetch()];
          if (onFeedbackStale) {
            refreshes.push(Promise.resolve().then(onFeedbackStale));
          }
          await Promise.allSettled(refreshes);
          if (requestIsCurrent()) setFeedbackStale(false);
          return;
        }
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json() as InsightFeedbackResponse;
      if (!requestIsCurrent()) return;
      setFeedbackVote(payload.feedback.vote);
      setFeedbackSent(true);
      setFeedbackOpen(false);
      setFeedbackComment('');
    } catch {
      if (requestIsCurrent()) {
        setFeedbackError(i18n._(msg`Couldn't send feedback. Try again.`));
      }
    } finally {
      if (requestIsCurrent()) setFeedbackSending(false);
    }
  };

  if (!content) return null;

  const skillName = insightType.replace(/_/g, '-');
  const hasDetails = content.findings.length > 0 || content.recommendations.length > 0;
  const toggleDetails = () => {
    if (!detailsOpen) onDetailsOpen?.();
    setDetailsOpen((value) => !value);
  };

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
            onClick={toggleDetails}
            aria-expanded={detailsOpen}
          >
            <span className="coach-toggle-caret" aria-hidden="true">{detailsOpen ? '▾' : '▸'}</span>
            {detailsOpen ? (
              <Trans>Hide details</Trans>
            ) : (
              <span>
                {content.findings.length > 0 && (
                  <Plural value={content.findings.length} one="# finding" other="# findings" />
                )}
                {content.findings.length > 0 && content.recommendations.length > 0 && <Trans> · </Trans>}
                {content.recommendations.length > 0 && (
                  <Plural value={content.recommendations.length} one="# recommendation" other="# recommendations" />
                )}
              </span>
            )}
          </button>
        )}
        {detailsOpen && content.findings.length > 0 && (
          <>
            <p className="coach-label"><Trans>Findings</Trans></p>
            <ul className="coach-list">
              {content.findings.map((finding, index) => (
                <li key={index} className={`coach-row coach-row-${finding.type}`}>
                  <span className="coach-tag" aria-hidden="true">[{finding.type === 'positive' ? '+' : finding.type === 'warning' ? '!' : '·'}]</span>
                  <span className="coach-text">{linkifyScienceTerms(finding.text)}</span>
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
              {content.recommendations.map((recommendation, index) => (
                <li key={index} className="coach-row">
                  <span className="coach-tag coach-tag-rec" aria-hidden="true">→</span>
                  <span className="coach-text">{linkifyScienceTerms(recommendation)}</span>
                </li>
              ))}
            </ol>
          </>
        )}
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
      {canCollectFeedback && (
        <div className={`coach-feedback-panel ${feedbackOpen ? 'is-open' : ''}`.trim()}>
          <div className="coach-feedback-toolbar">
            {feedbackSent ? (
              <span className="coach-feedback-sent font-data" role="status">
                <Check size={13} aria-hidden="true" /> <Trans>Sent</Trans>
              </span>
            ) : (
              <>
                <span className="coach-feedback-question"><Trans>Was this insight useful?</Trans></span>
                <div
                  className="coach-feedback-actions"
                  role="group"
                  aria-label={i18n._(msg`Was this insight useful?`)}
                >
                  <button
                    type="button"
                    className={`coach-feedback-icon ${feedbackVote === 'up' ? 'is-selected' : ''}`.trim()}
                    aria-label={i18n._(msg`Helpful`)}
                    aria-pressed={feedbackVote === 'up'}
                    disabled={feedbackSending || feedbackStale}
                    onClick={() => selectFeedback('up')}
                  >
                    <ThumbsUp size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className={`coach-feedback-icon ${feedbackVote === 'down' ? 'is-selected' : ''}`.trim()}
                    aria-label={i18n._(msg`Not helpful`)}
                    aria-pressed={feedbackVote === 'down'}
                    disabled={feedbackSending || feedbackStale}
                    onClick={() => selectFeedback('down')}
                  >
                    <ThumbsDown size={14} aria-hidden="true" />
                  </button>
                </div>
              </>
            )}
          </div>
          {feedbackOpen && !feedbackSent && (
            <div className="coach-feedback-form">
              <label className="sr-only" htmlFor={`coach-feedback-${insightType}`}>
                <Trans>Optional comment</Trans>
              </label>
              <textarea
                id={`coach-feedback-${insightType}`}
                value={feedbackComment}
                maxLength={200}
                rows={2}
                placeholder={i18n._(msg`What was useful or missing?`)}
                disabled={feedbackSending || feedbackStale}
                onChange={(event) => setFeedbackComment(event.target.value)}
              />
              <div className="coach-feedback-form-footer">
                <span className="coach-feedback-count font-data">{feedbackComment.length}/200</span>
                <button
                  type="button"
                  className="coach-feedback-cancel"
                  disabled={feedbackSending}
                  onClick={cancelFeedback}
                >
                  <Trans>Cancel</Trans>
                </button>
                <button
                  type="button"
                  className="coach-feedback-send"
                  disabled={feedbackSending || feedbackStale || !feedbackVote}
                  onClick={() => void sendFeedback()}
                >
                  {feedbackSending ? <Trans>Sending...</Trans> : <Trans>Send</Trans>}
                </button>
              </div>
              {feedbackError && (
                <p className="coach-feedback-error" role="alert">{feedbackError}</p>
              )}
            </div>
          )}
        </div>
      )}
      {attribution && <div className="coach-foot">{attribution}</div>}
    </aside>
  );
}
