import { useState, useEffect } from 'react';
import type { HistoryResponse } from '@/types/api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import ActivityCard from '@/components/ActivityCard';

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
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`/api/history?limit=${limit}&offset=${offset}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [offset]);

  const total = data?.total ?? 0;
  const showingFrom = total > 0 ? offset + 1 : 0;
  const showingTo = Math.min(offset + limit, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div>
      {/* Page header */}
      <div className="flex items-baseline justify-between mb-6">
        <h1 className="text-2xl font-bold">Activities</h1>
        {data && (
          <span className="text-sm text-muted-foreground">
            <span className="font-data">{total}</span> activities
          </span>
        )}
      </div>

      {loading && <HistorySkeleton />}

      {error && !loading && (
        <Alert variant="destructive">
          <AlertTitle>Failed to load activities</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {data && !loading && !error && (
        <>
          {data.activities.length === 0 ? (
            <p className="text-muted-foreground text-center py-12">
              No activities found.
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
                Previous
              </Button>

              <span className="text-sm text-muted-foreground">
                Showing{' '}
                <span className="font-data">
                  {showingFrom}&ndash;{showingTo}
                </span>{' '}
                of <span className="font-data">{total}</span>
              </span>

              <Button
                variant="outline"
                disabled={!hasNext}
                onClick={() => setOffset((o) => o + limit)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
