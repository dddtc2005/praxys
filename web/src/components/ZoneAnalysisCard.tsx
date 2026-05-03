import type { ZoneDistribution, ZoneRange, DisplayConfig } from '@/types/api';
import DistributionBar from '@/components/DistributionBar';
import { Trans, useLingui } from '@lingui/react/macro';
import { tDisplay } from '@/lib/display-labels';

interface Props {
  distribution: ZoneDistribution[];
  zoneRanges: ZoneRange[];
  theoryName: string;
  display?: DisplayConfig;
  /** Optional one-sentence theory description rendered as a muted
   *  caption beneath the eyebrow. Used to inline-explain theory names
   *  ("Seiler Polarized 3-Zone") that mean nothing to first-timers. */
  theoryDescription?: string;
}

// Zone gradient runs cool→warm with intensity. Uses only the semantic
// palette — no accent-blue/cobalt (cobalt is reserved for reasoning
// surfaces), no primary green dominating the bar (primary is the action
// signal, kept rare per the Restraint Rule). Aerobic zones stay in
// tinted ink; caution (threshold) and high-intensity (vo2max) earn
// warm color.
const ZONE_TEXT_COLORS = [
  'text-muted-foreground',
  'text-foreground/70',
  'text-foreground',
  'text-accent-amber',
  'text-destructive',
];

function getZoneTextColor(index: number, total: number) {
  const scaled = Math.round((index / Math.max(total - 1, 1)) * (ZONE_TEXT_COLORS.length - 1));
  return ZONE_TEXT_COLORS[scaled] ?? ZONE_TEXT_COLORS[0];
}

function formatRange(range: ZoneRange): string {
  if (range.upper == null) return `> ${range.lower}${range.unit}`;
  if (range.lower === 0) return `< ${range.upper}${range.unit}`;
  return `${range.lower}–${range.upper}${range.unit}`;
}

/**
 * Zone distribution panel — borderless content block (no Card chrome).
 * Owns the full zone story: theory description (optional) + visual
 * proportion bar + numeric breakdown table. Used as a tab in the
 * Diagnosis chart switcher on Training; flat-by-default.
 *
 * Note: deviation alerts that used to live here have moved into the
 * Praxys Coach receipt's rule-based fallback (single canonical
 * interpretation surface). Don't re-introduce the standalone Alert.
 */
export default function ZoneAnalysisCard({ distribution, zoneRanges, theoryName, display, theoryDescription }: Props) {
  const { i18n } = useLingui();
  const thresholdLabel = display ? `${display.threshold_abbrev}` : '';

  const rows = [...distribution].reverse();
  const ranges = [...zoneRanges].reverse();

  return (
    <div>
      {/* Tab label above already says "Zone distribution" — render only
          the theory attribution + threshold label here so the chart
          carries its analytical context without duplicating the title. */}
      <div className="flex items-center justify-between mb-1">
        <p className="text-[11px] text-muted-foreground">
          <Trans>vs {theoryName}</Trans>
        </p>
        {thresholdLabel && (
          <span className="text-[11px] text-muted-foreground font-data">{thresholdLabel}</span>
        )}
      </div>
      {theoryDescription ? (
        <p className="text-xs text-muted-foreground/80 leading-snug mb-4">
          {theoryDescription}
        </p>
      ) : (
        <div className="mb-3" />
      )}

      {/* Visual bar above the numeric table — same dataset, two
          presentations stacked: scan-fast bar on top, precise
          breakdown below. */}
      <div className="mb-5">
        <DistributionBar distribution={distribution} />
      </div>

      <div className="grid grid-cols-[5rem_1fr_3.5rem_3.5rem] items-center pb-2 mb-2 border-b border-border">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Zone</Trans></span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Range</Trans></span>
        <span className="text-right text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Actual</Trans></span>
        <span className="text-right text-[10px] uppercase tracking-wider text-muted-foreground"><Trans>Target</Trans></span>
      </div>

      <div className="space-y-1.5">
        {rows.map((d, i) => {
          const range = ranges[i];
          const colorClass = getZoneTextColor(distribution.length - 1 - i, distribution.length);
          return (
            <div key={d.name} className="grid grid-cols-[5rem_1fr_3.5rem_3.5rem] items-center">
              <span className={`text-sm font-medium ${colorClass}`}>{tDisplay(d.name, i18n)}</span>
              <span className="text-sm text-muted-foreground font-data tabular-nums truncate">
                {range ? formatRange(range) : ''}
              </span>
              <span className="text-right text-sm font-semibold font-data tabular-nums text-foreground">
                {d.actual_pct}%
              </span>
              <span className="text-right text-sm font-data tabular-nums text-muted-foreground">
                {d.target_pct != null ? `${d.target_pct}%` : '—'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
