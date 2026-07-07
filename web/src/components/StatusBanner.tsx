import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, AlertOctagon, X } from 'lucide-react';
import { Trans, useLingui } from '@lingui/react/macro';
import { useApi } from '@/hooks/useApi';
import type { ServiceStatus, OverallStatus } from '@/types/api';

const STORAGE_KEY = 'praxys_dismissed_status';

const BANNER: Partial<Record<OverallStatus, { wrap: string; Icon: typeof AlertTriangle; iconClass: string }>> = {
  degraded:       { wrap: 'bg-accent-amber/10 border-accent-amber/30', Icon: AlertTriangle, iconClass: 'text-accent-amber' },
  partial_outage: { wrap: 'bg-accent-amber/10 border-accent-amber/30', Icon: AlertTriangle, iconClass: 'text-accent-amber' },
  major_outage:   { wrap: 'bg-accent-red/10 border-accent-red/30',     Icon: AlertOctagon,  iconClass: 'text-accent-red' },
};

/**
 * App-wide incident banner for logged-in users. Invisible while everything is
 * operational — it only appears when GET /api/status reports a degradation or
 * outage, so healthy days stay uncluttered (unlike a persistent nav link).
 * Dismissible, but re-appears if the severity or active-incident set changes
 * (localStorage signature-keyed), so a worsening situation isn't silenced.
 */
export default function StatusBanner() {
  const { t } = useLingui();
  const { data } = useApi<ServiceStatus>('/api/status', { refetchInterval: 60000 });
  const [dismissedSig, setDismissedSig] = useState<string>(() => {
    try { return localStorage.getItem(STORAGE_KEY) ?? ''; } catch { return ''; }
  });

  const overall = data?.overall;
  const incidents = data?.incidents ?? [];

  const signature = useMemo(() => {
    if (!overall || overall === 'operational') return '';
    const ids = incidents.map((i) => `${i.id}:${i.status}`).sort().join(',');
    return `${overall}|${ids}`;
  }, [overall, incidents]);

  if (!overall || overall === 'operational') return null;
  const cfg = BANNER[overall];
  if (!cfg) return null;
  if (signature && signature === dismissedSig) return null;

  const { wrap, Icon, iconClass } = cfg;
  const headline = incidents[0]?.title || (
    overall === 'major_outage'
      ? t`Praxys is experiencing a major service outage.`
      : overall === 'partial_outage'
        ? t`Praxys is experiencing a partial service outage.`
        : t`Praxys is experiencing degraded performance.`
  );

  const dismiss = () => {
    try { localStorage.setItem(STORAGE_KEY, signature); } catch { /* ignore */ }
    setDismissedSig(signature);
  };

  return (
    <div className="space-y-2 px-4 pt-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
      <div className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${wrap}`}>
        <Icon className={`h-4 w-4 shrink-0 mt-0.5 ${iconClass}`} />
        <div className="flex-1 min-w-0">
          <span className="font-medium">{headline}</span>
          <Link to="/status" className="ml-2 underline underline-offset-2 font-medium hover:opacity-80">
            <Trans>View status</Trans>
          </Link>
        </div>
        <button
          onClick={dismiss}
          className="shrink-0 rounded p-0.5 hover:bg-black/10 transition-colors"
          aria-label={t`Dismiss`}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
