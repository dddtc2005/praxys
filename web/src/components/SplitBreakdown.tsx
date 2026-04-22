import type { SplitData } from '@/types/api';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Trans } from '@lingui/react/macro';

interface Props {
  splits: SplitData[];
  cpEstimate: number | null;
}

function powerZoneClass(power: number | null, cp: number | null): string {
  if (power == null || cp == null || cp <= 0) return 'text-muted-foreground';
  const pct = power / cp;
  if (pct >= 0.98) return 'text-destructive';
  if (pct >= 0.92) return 'text-accent-amber';
  if (pct >= 0.85) return 'text-accent-blue';
  return 'text-muted-foreground';
}

function formatSplitDuration(sec: number | null): string {
  if (sec == null) return '\u2014';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export default function SplitBreakdown({ splits, cpEstimate }: Props) {
  if (splits.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-2"><Trans>No split data available.</Trans></p>
    );
  }

  return (
    <div className="mt-4 border-t border-border pt-4 overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-left">#</TableHead>
            <TableHead className="text-right"><Trans>Dist</Trans></TableHead>
            <TableHead className="text-right"><Trans>Duration</Trans></TableHead>
            <TableHead className="text-right"><Trans>Power</Trans></TableHead>
            <TableHead className="text-right"><Trans>HR</Trans></TableHead>
            <TableHead className="text-right"><Trans>Pace</Trans></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {splits.map((s) => (
            <TableRow key={s.split_num}>
              <TableCell className="font-data text-muted-foreground">
                {s.split_num}
              </TableCell>
              <TableCell className="text-right font-data text-muted-foreground">
                {s.distance_km != null ? `${s.distance_km.toFixed(2)}` : '\u2014'}
              </TableCell>
              <TableCell className="text-right font-data text-muted-foreground">
                {formatSplitDuration(s.duration_sec)}
              </TableCell>
              <TableCell
                className={`text-right font-data font-medium ${powerZoneClass(s.avg_power, cpEstimate)}`}
              >
                {s.avg_power != null ? `${Math.round(s.avg_power)}` : '\u2014'}
              </TableCell>
              <TableCell className="text-right font-data text-muted-foreground">
                {s.avg_hr != null ? `${Math.round(s.avg_hr)}` : '\u2014'}
              </TableCell>
              <TableCell className="text-right font-data text-muted-foreground">
                {s.avg_pace_min_km ?? '\u2014'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
