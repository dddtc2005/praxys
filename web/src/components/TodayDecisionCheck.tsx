import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { msg } from '@lingui/core/macro';
import { Trans, useLingui } from '@lingui/react/macro';
import type { MessageDescriptor } from '@lingui/core';
import type { TodayFeedbackResponse } from '@/types/api';
import {
  claimTodayDecisionCheck,
  confirmTodayDecisionCheck,
  productEventStorageScope,
  recordProductEvent,
} from '@/lib/product-events';

const STORAGE_KEY = 'praxys:today-decision-check:last-shown';
const CADENCE_MS = 7 * 24 * 60 * 60 * 1000;

function cadenceStorageKey(): string {
  return `${STORAGE_KEY}:${productEventStorageScope()}`;
}

const OPTIONS: Array<{ value: TodayFeedbackResponse; label: MessageDescriptor }> = [
  { value: 'changed_plan', label: msg`Changed what I'll do` },
  { value: 'confirmed_plan', label: msg`Confirmed what I planned` },
  { value: 'not_helpful', label: msg`Didn't help today` },
  { value: 'not_training', label: msg`I'm not training today` },
];

function isDue(): boolean {
  try {
    const lastShown = Number(window.localStorage.getItem(cadenceStorageKey()) ?? 0);
    return !Number.isFinite(lastShown) || Date.now() - lastShown >= CADENCE_MS;
  } catch {
    return true;
  }
}

function localDayKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;
}

function markShown(): void {
  try {
    window.localStorage.setItem(cadenceStorageKey(), String(Date.now()));
  } catch {
    // Cadence persistence is best-effort when storage is unavailable.
  }
}

/** Low-frequency, one-tap check of whether Today affected the athlete's decision. */
export default function TodayDecisionCheck() {
  const { i18n } = useLingui();
  const [visible, setVisible] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const mountedDay = useRef(localDayKey()).current;

  useEffect(() => {
    if (!isDue()) return undefined;

    let cancelled = false;
    let claimStarted = false;
    const claimWhenVisible = () => {
      if (
        cancelled
        || claimStarted
        || document.visibilityState !== 'visible'
        || localDayKey() !== mountedDay
      ) return;
      claimStarted = true;
      void claimTodayDecisionCheck().then((claim) => {
        if (cancelled || claim === null || !claim.accepted || claim.duplicate) return;
        setVisible(true);
      });
    };
    claimWhenVisible();
    document.addEventListener('visibilitychange', claimWhenVisible);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', claimWhenVisible);
    };
  }, [mountedDay]);

  useEffect(() => {
    if (!visible) return undefined;
    let renderFrame = 0;
    let confirmFrame = 0;
    let confirmed = false;
    const confirmWhenVisible = () => {
      if (
        confirmed
        || renderFrame !== 0
        || confirmFrame !== 0
        || document.visibilityState !== 'visible'
      ) return;
      renderFrame = window.requestAnimationFrame(() => {
        renderFrame = 0;
        confirmFrame = window.requestAnimationFrame(() => {
          confirmFrame = 0;
          if (document.visibilityState !== 'visible') return;
          confirmed = true;
          markShown();
          void confirmTodayDecisionCheck();
        });
      });
    };
    confirmWhenVisible();
    document.addEventListener('visibilitychange', confirmWhenVisible);
    return () => {
      document.removeEventListener('visibilitychange', confirmWhenVisible);
      window.cancelAnimationFrame(renderFrame);
      window.cancelAnimationFrame(confirmFrame);
    };
  }, [visible]);

  if (!visible) return null;

  const submit = async (response: TodayFeedbackResponse) => {
    if (submitting) return;
    setSubmitting(true);
    setSubmitError('');
    const result = await recordProductEvent('today_feedback_submitted', response);
    if (result?.accepted) {
      markShown();
      setSubmitted(true);
    } else {
      setSubmitError(i18n._(msg`Couldn't send feedback. Try again.`));
    }
    setSubmitting(false);
  };

  if (submitted) {
    return (
      <section className="today-decision-check today-decision-check--thanks" aria-live="polite">
        <span className="today-decision-eyebrow font-data"><Trans>Quick check</Trans></span>
        <p><Trans>Thanks - that helps us improve Today.</Trans></p>
      </section>
    );
  }

  return (
    <section
      className={`today-decision-check ${expanded ? 'is-expanded' : ''}`.trim()}
      aria-labelledby="today-decision-heading"
      aria-busy={submitting}
    >
      <button
        type="button"
        className="today-decision-trigger"
        aria-expanded={expanded}
        aria-controls="today-decision-options"
        disabled={submitting}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="today-decision-copy">
          <span className="today-decision-eyebrow font-data"><Trans>Quick check</Trans></span>
          <span id="today-decision-heading" className="today-decision-heading">
            <Trans>Did today's brief affect your training decision?</Trans>
          </span>
        </span>
        <ChevronDown className="today-decision-chevron" size={16} aria-hidden="true" />
      </button>
      {expanded && (
        <div id="today-decision-options" className="today-decision-panel">
          <p className="today-decision-detail"><Trans>One tap helps us make this brief more useful.</Trans></p>
          <div className="today-decision-options">
            {OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className="today-decision-option"
                disabled={submitting}
                onClick={() => void submit(option.value)}
              >
                {i18n._(option.label)}
              </button>
            ))}
            {submitError && (
              <p className="today-decision-error" role="alert">{submitError}</p>
            )}
          </div>
          <button
            type="button"
            className="today-decision-dismiss"
            disabled={submitting}
            onClick={() => {
              setVisible(false);
              void confirmTodayDecisionCheck();
            }}
          >
            <Trans>Dismiss</Trans>
          </button>
        </div>
      )}
    </section>
  );
}