// Praxys brand mark — race flag on a cobalt pole. See docs/brand/index.html
// for the full brand guideline, including construction grid and clearspace.
//
// The pole leans forward 2 units on a 37-unit height; the flag's attachment
// edge follows the pole's angle so the flag appears to hang on the pole.

import type { SVGProps } from 'react';

type PraxysFlagProps = SVGProps<SVGSVGElement> & {
  /** Width of the cobalt pole stroke. Defaults to a size that reads well from 16 px to hero. */
  strokeWidth?: number;
};

export function PraxysFlag({ strokeWidth = 3, ...props }: PraxysFlagProps) {
  return (
    <svg viewBox="0 0 48 48" role="img" aria-label="Praxys" {...props}>
      <line
        x1="14"
        y1="42"
        x2="16"
        y2="5"
        stroke="var(--accent-cobalt-val)"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
      />
      <path
        d="M 16 6 L 40 8 Q 33 14, 40 20 L 15 22 Z"
        fill="var(--primary)"
      />
    </svg>
  );
}
