import { Link } from 'react-router-dom';
import { Trans, useLingui } from '@lingui/react/macro';
import {
  CheckCircle2,
  AlertTriangle,
  AlertOctagon,
  RefreshCw,
  ArrowLeft,
  WifiOff,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { useLocale } from '@/contexts/LocaleContext';
import type {
  ServiceStatus,
  ServiceIncident,
  IncidentUpdate,
  OverallStatus,
  ComponentStatus,
  IncidentImpact,
  IncidentStatus,
} from '@/types/api';

type BannerState = OverallStatus | 'unreachable';

/** Overall-banner presentation. Green = healthy, amber = degraded/partial,
 *  red = major/unreachable — matching the semantic palette (accent tokens). */
const OVERALL_STYLE: Record<BannerState, { Icon: typeof CheckCircle2; accent: string; ring: string }> = {
  operational:     { Icon: CheckCircle2,  accent: 'text-accent-green', ring: 'bg-accent-green/10 border-accent-green/30' },
  degraded:        { Icon: AlertTriangle, accent: 'text-accent-amber', ring: 'bg-accent-amber/10 border-accent-amber/30' },
  partial_outage:  { Icon: AlertTriangle, accent: 'text-accent-amber', ring: 'bg-accent-amber/10 border-accent-amber/30' },
  major_outage:    { Icon: AlertOctagon,  accent: 'text-accent-red',   ring: 'bg-accent-red/10 border-accent-red/30' },
  unreachable:     { Icon: WifiOff,       accent: 'text-accent-red',   ring: 'bg-accent-red/10 border-accent-red/30' },
};

const COMPONENT_DOT: Record<ComponentStatus, string> = {
  operational: 'bg-accent-green',
  degraded_performance: 'bg-accent-amber',
  partial_outage: 'bg-accent-amber',
  major_outage: 'bg-accent-red',
};

const IMPACT_STYLE: Record<IncidentImpact, string> = {
  minor: 'text-accent-amber border-accent-amber/40 bg-accent-amber/10',
  major: 'text-accent-amber border-accent-amber/40 bg-accent-amber/10',
  critical: 'text-accent-red border-accent-red/40 bg-accent-red/10',
};

export default function Status() {
  const { t } = useLingui();
  const { locale, setLocale } = useLocale();
  const zh = locale === 'zh';

  // Poll so an open status tab reflects new incidents without a manual reload.
  const { data, loading, error, refetch } = useApi<ServiceStatus>('/api/status', {
    refetchInterval: 30000,
  });
  const { data: history } = useApi<ServiceIncident[]>('/api/status/incidents?limit=20', {
    refetchInterval: 60000,
  });

  const fmt = (iso: string | null | undefined): string => {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString(zh ? 'zh-CN' : 'en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  };

  const overallLabel = (o: BannerState): string => {
    switch (o) {
      case 'operational': return t`All Systems Operational`;
      case 'degraded': return t`Degraded Performance`;
      case 'partial_outage': return t`Partial Outage`;
      case 'major_outage': return t`Major Outage`;
      case 'unreachable': return t`Unable to reach the status service`;
    }
  };

  const componentStatusLabel = (s: ComponentStatus): string => {
    switch (s) {
      case 'operational': return t`Operational`;
      case 'degraded_performance': return t`Degraded`;
      case 'partial_outage': return t`Partial outage`;
      case 'major_outage': return t`Outage`;
    }
  };

  const incidentStatusLabel = (s: IncidentStatus): string => {
    switch (s) {
      case 'investigating': return t`Investigating`;
      case 'identified': return t`Identified`;
      case 'monitoring': return t`Monitoring`;
      case 'resolved': return t`Resolved`;
    }
  };

  const impactLabel = (i: IncidentImpact): string => {
    switch (i) {
      case 'minor': return t`Minor`;
      case 'major': return t`Major`;
      case 'critical': return t`Critical`;
    }
  };

  const banner: BannerState = error ? 'unreachable' : (data?.overall ?? 'operational');
  const { Icon, accent, ring } = OVERALL_STYLE[banner];

  const activeIncidents = data?.incidents ?? [];
  const pastIncidents = (history ?? []).filter((i) => i.status === 'resolved');

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-6 py-12">
        {/* Top bar */}
        <div className="flex items-center justify-between mb-8">
          <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
            <ArrowLeft className="h-3.5 w-3.5" />
            <Trans>Back to Praxys</Trans>
          </Link>
          <button
            type="button"
            onClick={() => setLocale(zh ? 'en' : 'zh')}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            {zh ? 'EN' : '中文'}
          </button>
        </div>

        <h1 className="text-3xl font-semibold tracking-tight">Praxys</h1>
        <h2 className="mt-1 text-xl font-medium text-muted-foreground">
          <Trans>Service Status</Trans>
        </h2>

        {/* Overall banner */}
        <div className={`mt-8 flex items-center gap-4 rounded-xl border p-5 ${ring}`}>
          <Icon className={`h-8 w-8 shrink-0 ${accent}`} aria-hidden />
          <div className="min-w-0">
            <p className={`text-lg font-semibold ${accent}`}>{overallLabel(banner)}</p>
            <p className="mt-0.5 text-xs text-muted-foreground font-data">
              {error
                ? <Trans>The status API did not respond — this itself may indicate an outage.</Trans>
                : data?.updated_at
                  ? <><Trans>Last updated</Trans> {fmt(data.updated_at)}</>
                  : <Trans>Loading…</Trans>}
            </p>
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            aria-label={t`Refresh`}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            <Trans>Refresh</Trans>
          </button>
        </div>

        {/* Components */}
        <section className="mt-8">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            <Trans>Components</Trans>
          </h3>
          <div className="mt-3 divide-y divide-border rounded-lg border border-border">
            {(data?.components ?? []).map((c) => (
              <div key={c.key} className="flex items-center justify-between px-4 py-3">
                <span className="text-sm font-medium">{c.name}</span>
                <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <span className={`h-2.5 w-2.5 rounded-full ${COMPONENT_DOT[c.status]}`} />
                  {componentStatusLabel(c.status)}
                </span>
              </div>
            ))}
            {!data && !error && (
              <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                <Trans>Loading components…</Trans>
              </div>
            )}
            {error && (
              <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                <Trans>Component health is unavailable right now.</Trans>
              </div>
            )}
          </div>
        </section>

        {/* Active incidents */}
        {activeIncidents.length > 0 && (
          <section className="mt-8">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-accent-amber">
              <Trans>Active Incidents</Trans>
            </h3>
            <div className="mt-3 space-y-4">
              {activeIncidents.map((inc) => (
                <IncidentCard
                  key={inc.id}
                  incident={inc}
                  fmt={fmt}
                  impactLabel={impactLabel}
                  incidentStatusLabel={incidentStatusLabel}
                />
              ))}
            </div>
          </section>
        )}

        {/* Past incidents */}
        <section className="mt-8">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            <Trans>Past Incidents</Trans>
          </h3>
          {pastIncidents.length === 0 ? (
            <p className="mt-3 rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
              <Trans>No incidents reported recently.</Trans>
            </p>
          ) : (
            <div className="mt-3 space-y-4">
              {pastIncidents.map((inc) => (
                <IncidentCard
                  key={inc.id}
                  incident={inc}
                  fmt={fmt}
                  impactLabel={impactLabel}
                  incidentStatusLabel={incidentStatusLabel}
                  muted
                />
              ))}
            </div>
          )}
        </section>

        <div className="mt-10 pt-6 border-t border-border text-xs text-muted-foreground">
          <Trans>This page refreshes automatically every 30 seconds.</Trans>
        </div>
      </div>
    </div>
  );
}

function IncidentCard({
  incident,
  fmt,
  impactLabel,
  incidentStatusLabel,
  muted,
}: {
  incident: ServiceIncident;
  fmt: (iso: string | null | undefined) => string;
  impactLabel: (i: IncidentImpact) => string;
  incidentStatusLabel: (s: IncidentStatus) => string;
  muted?: boolean;
}) {
  return (
    <div className={`rounded-lg border border-border p-4 ${muted ? 'opacity-80' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${IMPACT_STYLE[incident.impact]}`}>
              {impactLabel(incident.impact)}
            </span>
            <h4 className="text-sm font-semibold truncate">{incident.title}</h4>
          </div>
          <p className="mt-1 text-xs text-muted-foreground font-data">
            {incident.status === 'resolved' && incident.resolved_at
              ? <><Trans>Resolved</Trans> · {fmt(incident.resolved_at)}</>
              : <><Trans>Started</Trans> · {fmt(incident.started_at)}</>}
          </p>
        </div>
      </div>

      {/* Timeline */}
      {incident.updates.length > 0 && (
        <ol className="mt-3 space-y-3 border-l border-border pl-4">
          {incident.updates.map((u: IncidentUpdate) => (
            <li key={u.id} className="relative">
              <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-muted-foreground/60" />
              <p className="text-xs font-semibold text-foreground">
                {incidentStatusLabel(u.status)}
              </p>
              <p className="text-xs text-muted-foreground">{u.body}</p>
              <p className="mt-0.5 text-[10px] text-muted-foreground/70 font-data">{fmt(u.created_at)}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
