import { Link } from 'react-router-dom';
import { useApi } from '@/hooks/useApi';
import { useLingui } from '@lingui/react/macro';
import type { ServiceStatus, OverallStatus } from '@/types/api';

// Semantic status colours (theme tokens, not raw hex). Degraded and partial
// share amber; major is red. Unknown/loading/error falls back to a neutral dot.
const DOT_VAR: Record<OverallStatus, string> = {
  operational: 'var(--color-accent-green)',
  degraded: 'var(--color-accent-amber)',
  partial_outage: 'var(--color-accent-amber)',
  major_outage: 'var(--color-accent-red)',
};

/**
 * Compact live service-status pill: a colour-coded dot + short label that
 * links to the public /status page. Backed by the public GET /api/status
 * endpoint, so it renders for logged-out visitors too. Polls every 60s.
 */
export default function StatusIndicator({ className }: { className?: string }) {
  const { t } = useLingui();
  const { data, error } = useApi<ServiceStatus>('/api/status', { refetchInterval: 60000 });
  const overall = error ? undefined : data?.overall;

  const label = (): string => {
    switch (overall) {
      case 'operational': return t`All systems operational`;
      case 'degraded': return t`Degraded performance`;
      case 'partial_outage': return t`Partial service outage`;
      case 'major_outage': return t`Major service outage`;
      default: return t`Service status`;
    }
  };
  const dot = overall ? DOT_VAR[overall] : 'var(--color-muted-foreground)';

  return (
    <Link
      to="/status"
      aria-label={t`Service status`}
      className={`inline-flex items-center gap-1.5 ${className ?? ''}`}
    >
      <span aria-hidden style={{ background: dot }} className="inline-block h-2 w-2 rounded-full" />
      <span>{label()}</span>
    </Link>
  );
}
