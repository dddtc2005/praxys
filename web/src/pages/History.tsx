import { useState } from 'react';
import { useApi } from '@/hooks/useApi';
import type { HistoryResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import ActivityCard from '@/components/ActivityCard';
import { Trans, Plural } from '@lingui/react/macro';

function HistorySkeleton() {
  return (
    <div className="space-y-3">
      {[...Array(5)].map((_, i) => (
        <Skeleton key={i} className="h-32 rounded-2xl" />
      ))}
    </div>
  );
}

export default function History() {
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const { data, loading, error, refetch } = useApi<HistoryResponse>(
    `/api/history?limit=${limit}&offset=${offset}`
  );

  const total = data?.total ?? 0;
  const showingFrom = total > 0 ? offset + 1 : 0;
  const showingTo = Math.min(offset + limit, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div>
      {/* Page header */}
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-2xl font-bold"><Trans>Activities</Trans></h1>
        {data && (
          <span className="text-sm text-muted-foreground">
            <Plural value={total} one="# activity" other="# activities" />
          </span>
        )}
      </div>

      {loading && <HistorySkeleton />}

      {error && !loading && (
        <Alert variant="destructive">
          <AlertTitle><Trans>Failed to load activities</Trans></AlertTitle>
          <AlertDescription className="flex items-center justify-between">
            <span>{error}</span>
            <Button variant="outline" size="sm" onClick={() => refetch()}><Trans>Retry</Trans></Button>
          </AlertDescription>
        </Alert>
      )}

      {data && !loading && !error && (
        <>
          {data.activities.length === 0 ? (
            <p className="text-muted-foreground text-center py-12">
              <Trans>No activities found.</Trans>
            </p>
          ) : (
            <div className="space-y-3">
              {data.activities.map((activity) => (
                <ActivityCard key={activity.activity_id} activity={activity} />
              ))}
            </div>
          )}

          {/* Pagination controls */}
          {total > limit && (
            <div className="flex items-center justify-between mt-6 pt-4 border-t border-border">
              <Button
                variant="outline"
                disabled={!hasPrev}
                onClick={() => setOffset((o) => Math.max(0, o - limit))}
              >
                <Trans>Previous</Trans>
              </Button>

              <span className="text-sm text-muted-foreground">
                <Trans>Showing</Trans>{' '}
                <span className="font-data">
                  {showingFrom}&ndash;{showingTo}
                </span>{' '}
                <Trans>of</Trans> <span className="font-data">{total}</span>
              </span>

              <Button
                variant="outline"
                disabled={!hasNext}
                onClick={() => setOffset((o) => o + limit)}
              >
                <Trans>Next</Trans>
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
