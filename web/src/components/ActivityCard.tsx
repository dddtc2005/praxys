import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { Activity } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible';
import SplitBreakdown from '@/components/SplitBreakdown';

interface Props {
  activity: Activity;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function formatDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0)
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatActivityType(type: string): string {
  return type
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export default function ActivityCard({ activity }: Props) {
  const [expanded, setExpanded] = useState(false);

  const hasSplits = activity.splits.length > 0;

  return (
    <Card className={hasSplits ? 'hover:bg-muted/50 transition-colors' : ''}>
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <CardContent
          className={`pt-5 ${hasSplits ? 'cursor-pointer' : ''}`}
          onClick={() => { if (hasSplits) setExpanded((v) => !v); }}
        >
          {/* Header: date + type badge */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {formatDate(activity.date)}
              </span>
              <Badge variant="secondary">
                {formatActivityType(activity.activity_type)}
              </Badge>
            </div>
            {hasSplits && (
              <span className="text-muted-foreground">
                {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
              </span>
            )}
          </div>

          {/* Key metrics row */}
          <div className="flex flex-wrap gap-x-6 gap-y-2 mb-2">
            {activity.distance_km != null && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wider">
                  Distance
                </span>
                <p className="font-data text-lg font-semibold text-foreground">
                  {activity.distance_km.toFixed(1)}{' '}
                  <span className="text-xs text-muted-foreground font-normal">km</span>
                </p>
              </div>
            )}
            {activity.duration_sec != null && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wider">
                  Duration
                </span>
                <p className="font-data text-lg font-semibold text-foreground">
                  {formatDuration(activity.duration_sec)}
                </p>
              </div>
            )}
            {activity.avg_power != null && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wider">
                  Avg Power
                </span>
                <p className="font-data text-lg font-semibold text-foreground">
                  {Math.round(activity.avg_power)}{' '}
                  <span className="text-xs text-muted-foreground font-normal">W</span>
                </p>
              </div>
            )}
            {activity.avg_hr != null && (
              <div>
                <span className="text-xs text-muted-foreground uppercase tracking-wider">
                  Avg HR
                </span>
                <p className="font-data text-lg font-semibold text-foreground">
                  {Math.round(activity.avg_hr)}{' '}
                  <span className="text-xs text-muted-foreground font-normal">bpm</span>
                </p>
              </div>
            )}
          </div>

          {/* Secondary metrics */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {activity.avg_pace_min_km != null && (
              <span>
                Pace{' '}
                <span className="font-data">{activity.avg_pace_min_km}</span>{' '}
                /km
              </span>
            )}
            {activity.elevation_gain_m != null && (
              <span>
                Elev{' '}
                <span className="font-data">
                  {Math.round(activity.elevation_gain_m)}
                </span>{' '}
                m
              </span>
            )}
            {activity.rss != null && (
              <span>
                RSS{' '}
                <span className="font-data">{Math.round(activity.rss)}</span>
              </span>
            )}
            {activity.cp_estimate != null && (
              <span>
                CP{' '}
                <span className="font-data">{Math.round(activity.cp_estimate)}</span>{' '}
                W
              </span>
            )}
          </div>
        </CardContent>

        {/* Expandable splits */}
        <CollapsibleContent>
          <div className="px-6 pb-5">
            <SplitBreakdown
              splits={activity.splits}
              cpEstimate={activity.cp_estimate}
            />
          </div>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
