import type { WeekLoad } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props {
  weekLoad: WeekLoad;
}

export default function WeeklyLoadMini({ weekLoad }: Props) {
  const { actual, planned } = weekLoad;

  const pct = planned && planned > 0 ? Math.round((actual / planned) * 100) : null;

  let statusColor = 'text-primary';
  let barColor = 'bg-primary';
  if (pct != null) {
    if (pct > 120) {
      statusColor = 'text-destructive';
      barColor = 'bg-destructive';
    } else if (pct < 70) {
      statusColor = 'text-accent-amber';
      barColor = 'bg-accent-amber';
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Weekly Load
        </CardTitle>
        {weekLoad.week_label && (
          <span className="text-[10px] text-muted-foreground font-data">{weekLoad.week_label}</span>
        )}
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2 mb-3">
          <span className="text-2xl font-bold font-data text-foreground">
            {Math.round(actual)}
          </span>
          {planned != null && (
            <span className="text-sm text-muted-foreground font-data">
              / {Math.round(planned)} RSS
            </span>
          )}
          {pct != null && (
            <span className={`text-sm font-semibold font-data ml-auto ${statusColor}`}>
              {pct}%
            </span>
          )}
        </div>
        {pct != null && (
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${barColor}`}
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
        )}
        {planned == null && (
          <p className="text-xs text-muted-foreground">No planned load this week</p>
        )}
      </CardContent>
    </Card>
  );
}
