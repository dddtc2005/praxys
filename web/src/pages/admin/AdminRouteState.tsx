import type { ReactNode } from 'react';
import { AlertCircle } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Trans } from '@lingui/react/macro';

export function AdminRouteSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-24 rounded-xl" />
      <Skeleton className="h-56 rounded-xl" />
      <Skeleton className="h-56 rounded-xl" />
    </div>
  );
}

interface AdminRouteErrorProps {
  title: ReactNode;
  description: ReactNode;
  error?: string | null;
  onRetry: () => void | Promise<void>;
}

export function AdminRouteError({ title, description, error, onRetry }: AdminRouteErrorProps) {
  return (
    <Alert variant="destructive" className="rounded-xl border-destructive/30">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <div className="space-y-3">
          <p>{description}</p>
          {error ? <p className="font-data text-xs text-destructive/90">{error}</p> : null}
          <Button type="button" variant="outline" size="sm" onClick={() => void onRetry()}>
            <Trans>Retry</Trans>
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}

interface AdminEmptyStateProps {
  title: ReactNode;
  description: ReactNode;
  action?: ReactNode;
}

export function AdminEmptyState({ title, description, action }: AdminEmptyStateProps) {
  return (
    <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <p className="mt-2 text-sm text-muted-foreground">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
