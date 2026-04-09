import type { LastActivity } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface Props {
  activity: LastActivity;
}

function formatDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function LastActivityCard({ activity }: Props) {
  const details: string[] = [];
  if (activity.distance_km != null)
    details.push(`${activity.distance_km.toFixed(1)} km`);
  if (activity.duration_sec != null)
    details.push(formatDuration(activity.duration_sec));
  if (activity.avg_power != null)
    details.push(`${activity.avg_power} W`);
  else if (activity.avg_pace_min_km)
    details.push(`${activity.avg_pace_min_km} /km`);

  const typeLabel = activity.activity_type
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

  const dateLabel = new Date(activity.date).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Last Activity
        </CardTitle>
        <span className="text-[10px] text-muted-foreground font-data">{dateLabel}</span>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-2 mb-2">
          <Badge variant="secondary" className="text-[10px]">{typeLabel}</Badge>
          {activity.rss != null && (
            <span className="text-xs text-muted-foreground font-data">
              RSS {Math.round(activity.rss)}
            </span>
          )}
        </div>
        <p className="text-lg font-bold font-data text-foreground">
          {details.join(' \u00b7 ')}
        </p>
      </CardContent>
    </Card>
  );
}
