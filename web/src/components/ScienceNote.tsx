import { useState } from 'react';
import { Trans, useLingui } from '@lingui/react/macro';

/**
 * Inline progressive-disclosure reasoning surface \u2014 sits at the bottom of
 * metric cards as a default-collapsed "How this is calculated" affordance.
 *
 * Cobalt is the only signal that this is a reasoning surface (per the
 * Reasoning Color Rule in DESIGN.md). The trigger and the citation link
 * both use `text-accent-cobalt`; the expanded body stays in
 * `text-muted-foreground` because the prose is supporting context, not
 * the reasoning *signal*.
 *
 * Don't dress this up with eyebrows, banners, or a cobalt left rail \u2014
 * that pattern has been retired (it became the AI-UI clich\u00e9). For
 * standalone narrative reasoning surfaces use the `coach-receipt`
 * component instead.
 */
export default function ScienceNote({ text, sourceUrl, sourceLabel }: { text: string; sourceUrl?: string; sourceLabel?: string }) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useLingui();
  return (
    <div className="mt-4 pt-3 border-t border-border">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-[12px] text-accent-cobalt hover:text-accent-cobalt/80 transition-colors"
      >
        {expanded ? '\u25be' : '\u25b8'} <Trans>How this is calculated</Trans>
      </button>
      {expanded && (
        <p className="text-[13px] text-muted-foreground mt-2 leading-relaxed">
          {text}{' '}
          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-cobalt underline-offset-2 hover:underline"
            >
              {sourceLabel || t`Source`}
            </a>
          )}
        </p>
      )}
    </div>
  );
}
