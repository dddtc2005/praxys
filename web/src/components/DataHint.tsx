import { Card, CardContent } from '@/components/ui/card';
import { Info } from 'lucide-react';

interface DataHintProps {
  /** Whether the data is sufficient to show the chart. */
  sufficient: boolean;
  /** Message to show when data is insufficient. */
  message: string;
  /** Optional secondary hint (e.g., "Sync 6+ weeks of data"). */
  hint?: string;
  /** The chart component to render when data is sufficient. */
  children: React.ReactNode;
}

/**
 * Wraps a chart component and shows a helpful message when
 * there isn't enough data for meaningful visualization.
 */
export default function DataHint({ sufficient, message, hint, children }: DataHintProps) {
  if (sufficient) return <>{children}</>;

  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-8">
        <Info className="h-5 w-5 shrink-0 text-muted-foreground" />
        <div>
          <p className="text-sm text-muted-foreground">{message}</p>
          {hint && <p className="text-xs text-muted-foreground/70 mt-0.5">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  );
}
