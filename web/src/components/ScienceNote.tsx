import { useState } from 'react';
import { Trans, useLingui } from '@lingui/react/macro';

export default function ScienceNote({ text, sourceUrl, sourceLabel }: { text: string; sourceUrl?: string; sourceLabel?: string }) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useLingui();
  return (
    <div className="mt-3 pt-3 border-t border-border">
      <button onClick={() => setExpanded(!expanded)} className="text-[10px] text-muted-foreground hover:text-muted-foreground transition-colors">
        {expanded ? '\u25be' : '\u25b8'} <Trans>How this is calculated</Trans>
      </button>
      {expanded && (
        <p className="text-[10px] text-muted-foreground mt-1 leading-relaxed">
          {text}{' '}
          {sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="underline hover:text-muted-foreground">{sourceLabel || t`Source`}</a>}
        </p>
      )}
    </div>
  );
}
