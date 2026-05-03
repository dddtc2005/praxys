import type { ZoneDistribution, ZoneRange, DisplayConfig } from '@/types/api';
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
// muted ink; threshold earns amber, high-intensity earns destructive.
const ZONE_BAR_COLORS = [
  'bg-muted-foreground/40',
  'bg-muted-foreground/55',
  'bg-foreground/65',
  'bg-accent-amber',
  'bg-destructive',
];

const ZONE_TEXT_COLORS = [
  'text-muted-foreground',
  'text-foreground/70',
  'text-foreground',
  'text-accent-amber',
  'text-destructive',
];

function scaledIndex(index: number, total: number, max: number) {
  return Math.round((index / Math.max(total - 1, 1)) * (max - 1));
}

function formatRange(range: ZoneRange): string {
  if (range.upper == null) return `≥ ${range.lower}${range.unit}`;
  if (range.lower === 0) return `< ${range.upper}${range.unit}`;
  return `${range.lower}–${range.upper}${range.unit}`;
}

/**
 * Zone distribution panel — borderless content block (no Card chrome).
 * One row per zone: name on the left, a horizontal "actual fills /
 * target tick" bar in the middle, and `actual% / target%` on the right.
 * Mirrors the WeChat Mini Program's zone-distribution layout so the
 * two surfaces read the same.
 *
 * Why this and not a 4-col table: the bar makes "are you at, above,
 * or below target?" a one-glance read. Numbers stay precise but stop
 * being the only path to the answer.
 *
 * Note: deviation alerts that used to live here have moved into the
 * Praxys Coach receipt's rule-based fallback (single canonical
 * interpretation surface). Don't re-introduce the standalone Alert.
 */
export default function ZoneAnalysisCard({ distribution, zoneRanges, theoryName, display, theoryDescription }: Props) {
  const { i18n } = useLingui();
  const thresholdLabel = display ? display.threshold_abbrev : '';
  // Zones come in ascending intensity from the API; the visual ladder
  // reads better top-to-bottom from easiest to hardest, so keep order.
  const rows = distribution.map((d, i) => ({
    distribution: d,
    range: zoneRanges[i],
    barColor: ZONE_BAR_COLORS[scaledIndex(i, distribution.length, ZONE_BAR_COLORS.length)] ?? ZONE_BAR_COLORS[0],
    textColor: ZONE_TEXT_COLORS[scaledIndex(i, distribution.length, ZONE_TEXT_COLORS.length)] ?? ZONE_TEXT_COLORS[0],
  }));

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <p className="text-[11px] text-muted-foreground">
          <Trans>vs {theoryName}</Trans>
        </p>
        {thresholdLabel && (
          <span className="text-[11px] text-muted-foreground font-data">{thresholdLabel}</span>
        )}
      </div>
      {theoryDescription ? (
        <p className="text-xs text-muted-foreground/80 leading-snug mb-5">
          {theoryDescription}
        </p>
      ) : (
        <div className="mb-4" />
      )}

      <div className="space-y-4">
        {rows.map(({ distribution: d, range, barColor, textColor }) => {
          const actual = Math.max(0, Math.min(100, d.actual_pct));
          const target = d.target_pct != null
            ? Math.max(0, Math.min(100, d.target_pct))
            : null;
          return (
            <div key={d.name}>
              <div className="flex items-baseline justify-between mb-1.5">
                <div className="flex items-baseline gap-2">
                  <span className={`text-sm font-medium ${textColor}`}>
                    {tDisplay(d.name, i18n)}
                  </span>
                  {range && (
                    <span className="text-[11px] text-muted-foreground/80 font-data tabular-nums">
                      {formatRange(range)}
                    </span>
                  )}
                </div>
                <span className="text-[12px] font-data tabular-nums">
                  <span className="text-foreground font-semibold">{d.actual_pct}%</span>
                  <span className="text-muted-foreground/70"> / {target != null ? `${target}%` : '—'}</span>
                </span>
              </div>
              {/* Track + actual fill + target tick. The track is muted,
                  the fill is the zone's semantic color at full opacity,
                  and the tick is a thin foreground line at `target_pct`
                  so over/under-target becomes visible at a glance. */}
              <div className="relative h-2 rounded-full bg-muted/70 overflow-hidden">
                <div
                  className={`absolute inset-y-0 left-0 ${barColor} rounded-full transition-[width]`}
                  style={{ width: `${actual}%` }}
                />
                {target != null && (
                  <div
                    className="absolute inset-y-0 w-px bg-foreground/70"
                    style={{ left: `${target}%` }}
                    aria-label={`target ${target}%`}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
