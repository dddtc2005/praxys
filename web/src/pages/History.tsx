import { useState, useEffect } from 'react';
import type { HistoryResponse } from '@/types/api';
import ActivityCard from '@/components/ActivityCard';

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

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="rounded-2xl bg-card p-6 text-center">
          <p className="text-destructive font-medium mb-1">
            Failed to load activities
          </p>
          <p className="text-sm text-muted-foreground">{error}</p>
        </div>
      )}

      {/* Activity feed */}
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
              <button
                type="button"
                disabled={!hasPrev}
                onClick={() => setOffset((o) => Math.max(0, o - limit))}
                className={`rounded-lg px-4 py-2 text-sm font-medium bg-card hover:bg-muted transition-colors ${
                  !hasPrev ? 'opacity-50 cursor-not-allowed' : ''
                }`}
              >
                Previous
              </button>

              <span className="text-sm text-muted-foreground">
                Showing{' '}
                <span className="font-data">
                  {showingFrom}&ndash;{showingTo}
                </span>{' '}
                of <span className="font-data">{total}</span>
              </span>

              <button
                type="button"
                disabled={!hasNext}
                onClick={() => setOffset((o) => o + limit)}
                className={`rounded-lg px-4 py-2 text-sm font-medium bg-card hover:bg-muted transition-colors ${
                  !hasNext ? 'opacity-50 cursor-not-allowed' : ''
                }`}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
