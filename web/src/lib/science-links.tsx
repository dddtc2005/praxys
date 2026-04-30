/**
 * When the Praxys Coach cites a science theory by name, render that name as
 * a link to the corresponding section of the Science page.
 *
 * The map is intentionally keyed on the canonical theory names from
 * ``data/science/*.yaml`` (load.banister_pmc.name = "Banister PMC", etc.).
 * The Coach prompt rules instruct the model to cite by these exact names,
 * so we can match them as literal substrings without false positives.
 *
 * Why a static map (not API-driven): theory names ship with the codebase,
 * not user data — adding a new theory means editing this file alongside
 * the YAML, which is a one-line change. The simplicity beats one extra
 * fetch on every Coach card render.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

export const SCIENCE_PILLAR_LINKS: Record<string, string> = {
  // Load model
  'Banister PMC': '/science#load',
  'Banister TSB': '/science#load',
  // Recovery model — canonical name + a couple of common LLM paraphrases.
  'Plews HRV-guided': '/science#recovery',
  'Plews HRV trend': '/science#recovery',
  'Plews HRV': '/science#recovery',
  'HRV-Based Recovery': '/science#recovery',
  // Race-prediction model
  'Critical Power Model': '/science#prediction',
  'Critical Power': '/science#prediction',
  'Riegel': '/science#prediction',
  // Zone framework
  'Coggan 5-zone': '/science#zones',
  'Seiler Polarized': '/science#zones',
  'Seiler 3-zone': '/science#zones',
};

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Split ``text`` and wrap matched science-pillar names in <Link> elements
 * pointing at the relevant Science-page anchor. Returns a ReactNode array
 * suitable for passing as a child to a <p> / <span> / etc.
 *
 * The link uses the project's "reasoning" accent (cobalt) per the design
 * system rule that science citations live on the cobalt scale.
 */
export function linkifyScienceTerms(text: string): ReactNode[] {
  if (!text) return [text];
  // Sort longest-first so "Critical Power Model" matches before "Critical Power".
  const names = Object.keys(SCIENCE_PILLAR_LINKS).sort(
    (a, b) => b.length - a.length,
  );
  const pattern = new RegExp(`(${names.map(escapeRegex).join('|')})`, 'g');

  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  for (const match of text.matchAll(pattern)) {
    const idx = match.index ?? 0;
    if (idx > lastIndex) {
      parts.push(text.slice(lastIndex, idx));
    }
    const name = match[1];
    parts.push(
      <Link
        key={`sci-${key++}`}
        to={SCIENCE_PILLAR_LINKS[name]}
        className="text-accent-cobalt underline-offset-2 hover:underline"
      >
        {name}
      </Link>,
    );
    lastIndex = idx + name.length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length === 0 ? [text] : parts;
}
