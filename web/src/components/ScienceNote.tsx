import { useState } from 'react';

export default function ScienceNote({ text, sourceUrl, sourceLabel }: { text: string; sourceUrl?: string; sourceLabel?: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-3 pt-3 border-t border-border">
      <button onClick={() => setExpanded(!expanded)} className="text-[10px] text-text-muted hover:text-text-secondary transition-colors">
        {expanded ? '\u25be' : '\u25b8'} How this is calculated
      </button>
      {expanded && (
        <p className="text-[10px] text-text-muted mt-1 leading-relaxed">
          {text}{' '}
          {sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="underline hover:text-text-secondary">{sourceLabel || 'Source'}</a>}
        </p>
      )}
    </div>
  );
}
