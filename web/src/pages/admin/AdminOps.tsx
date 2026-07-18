import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  CloudOff,
  Database,
  ExternalLink,
  MessageSquareWarning,
  RefreshCw,
  Server,
  ShieldAlert,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useApi } from '@/hooks/useApi';
import { cn } from '@/lib/utils';
import { Trans, useLingui } from '@lingui/react/macro';
import type {
  AdminOpsFreshness,
  AdminOpsReason,
  AdminOpsSectionMeta,
  AdminOpsSectionWindow,
  AdminOpsSummary,
  AdminOpsWindow,
  ComponentStatus,
  OverallStatus,
} from '@/types/api';
import { AdminRouteError } from './AdminRouteState';

const WINDOWS: AdminOpsWindow[] = ['24h', '7d', '28d'];

const COMPONENT_DOT: Record<ComponentStatus, string> = {
  operational: 'bg-primary',
  degraded_performance: 'bg-accent-amber',
  partial_outage: 'bg-accent-amber',
  major_outage: 'bg-accent-red',
};

const OVERALL_ICON: Record<OverallStatus, typeof CheckCircle2> = {
  operational: CheckCircle2,
  degraded: AlertTriangle,
  partial_outage: AlertTriangle,
  major_outage: AlertOctagon,
};

const OVERALL_TONE: Record<OverallStatus, string> = {
  operational: 'text-primary',
  degraded: 'text-accent-amber',
  partial_outage: 'text-accent-amber',
  major_outage: 'text-accent-red',
};

type AttentionTone = 'clear' | 'warning' | 'critical' | 'unavailable';

const ATTENTION_TONE: Record<AttentionTone, { icon: string; title: string }> = {
  clear: { icon: 'bg-primary/10 text-primary', title: 'text-foreground' },
  warning: { icon: 'bg-accent-amber/10 text-accent-amber', title: 'text-foreground' },
  critical: { icon: 'bg-accent-red/10 text-accent-red', title: 'text-accent-red' },
  unavailable: { icon: 'bg-muted text-muted-foreground', title: 'text-foreground' },
};

function formatTimestamp(value: string | null, locale: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function AdminOpsSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-72" />
        </div>
        <Skeleton className="h-8 w-52" />
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="flex items-center gap-4 border-b border-border px-4 py-4 last:border-b-0">
            <Skeleton className="h-9 w-9 rounded-lg" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-44" />
              <Skeleton className="h-3 w-72" />
            </div>
            <Skeleton className="h-7 w-24" />
          </div>
        ))}
      </div>
      <div className="grid gap-8 xl:grid-cols-2">
        <Skeleton className="h-64 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    </div>
  );
}

function SectionMeta({ meta, stale = false, className }: { meta: AdminOpsSectionMeta; stale?: boolean; className?: string }) {
  const { t, i18n } = useLingui();
  const effectiveFreshness = stale && meta.freshness === 'fresh' ? 'stale' : meta.freshness;
  const freshnessClass =
    effectiveFreshness === 'fresh'
      ? 'border-primary/30 text-primary'
      : effectiveFreshness === 'stale'
        ? 'border-accent-amber/40 text-accent-amber'
        : 'border-border text-muted-foreground';

  const freshnessLabel = (freshness: AdminOpsFreshness): string => {
    switch (freshness) {
      case 'fresh':
        return t`Up to date`;
      case 'stale':
        return t`Stale`;
      case 'unavailable':
        return t`Unavailable`;
    }
  };

  const sourceLabel = (): string => {
    switch (meta.source) {
      case 'praxys_database':
        return t`Praxys database`;
      case 'live_probe':
        return t`Live probe`;
      case 'azure_monitor':
        return t`Azure Monitor`;
    }
  };

  const windowLabel = (window: AdminOpsSectionWindow): string => {
    switch (window) {
      case 'live':
        return t`Live`;
      case 'rolling_1d_7d_30d':
        return t`Rolling 1 / 7 / 30 days`;
      case '24h':
        return t`24 hours`;
      case '7d':
        return t`7 days`;
      case '28d':
        return t`28 days`;
    }
  };

  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground', className)}>
      <Badge variant="outline" className={cn('h-5 font-data', freshnessClass)}>
        {freshnessLabel(effectiveFreshness)}
      </Badge>
      <span>{sourceLabel()}</span>
      <span className="font-data">{windowLabel(meta.window)}</span>
      {meta.as_of ? (
        <span className="font-data">
          <Trans>Updated {formatTimestamp(meta.as_of, i18n.locale)}</Trans>
        </span>
      ) : null}
    </div>
  );
}

function AttentionRow({
  Icon,
  tone,
  title,
  description,
  detail,
  to,
  href,
  action,
}: {
  Icon: typeof CheckCircle2;
  tone: AttentionTone;
  title: string;
  description: string;
  detail?: string;
  to?: string;
  href?: string;
  action: string;
}) {
  const styles = ATTENTION_TONE[tone];
  const actionContent = (
    <>
      <span>{action}</span>
      {href ? <ExternalLink className="h-3.5 w-3.5" /> : <ArrowUpRight className="h-3.5 w-3.5" />}
    </>
  );

  return (
    <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center">
      <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg', styles.icon)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className={cn('text-sm font-semibold', styles.title)}>{title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        {detail ? <p className="mt-1 truncate text-xs text-foreground">{detail}</p> : null}
      </div>
      {to ? (
        <Link
          to={to}
          className="inline-flex shrink-0 items-center gap-1.5 text-xs font-medium text-primary hover:underline"
        >
          {actionContent}
        </Link>
      ) : href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-1.5 text-xs font-medium text-accent-cobalt hover:underline"
        >
          {actionContent}
        </a>
      ) : null}
    </div>
  );
}

export default function AdminOps() {
  const { t, i18n } = useLingui();
  const [window, setWindow] = useState<AdminOpsWindow>('24h');
  const { data, loading, stale, error, refetch } = useApi<AdminOpsSummary>(
    `/api/admin/ops/summary?window=${window}`,
    {
      refetchInterval: 60000,
      refetchOnMount: 'always',
      refetchOnWindowFocus: 'always',
    },
  );

  if (loading) {
    return <AdminOpsSkeleton />;
  }

  if (!data) {
    return (
      <AdminRouteError
        title={t`Couldn't load operations summary`}
        description={t`Management routes remain available. Retry the aggregate health snapshot.`}
        error={error}
        onRetry={refetch}
      />
    );
  }

  const localizedReason = (reason: AdminOpsReason | null, fallback: string): string =>
    reason === 'azure_telemetry_not_connected'
      ? t`Curated Azure Monitor summaries are unavailable until the telemetry trust boundary in issue #417 is separated.`
      : fallback;

  const attention = data.attention.data;
  const incidents = attention?.incident_counts;
  const feedback = attention?.feedback;
  const incidentTone: AttentionTone = !incidents
    ? 'unavailable'
    : incidents.critical > 0
      ? 'critical'
      : incidents.total > 0
        ? 'warning'
        : 'clear';
  const feedbackTone: AttentionTone = !feedback
    ? 'unavailable'
    : feedback.critical > 0
      ? 'critical'
      : feedback.actionable > 0
        ? 'warning'
        : 'clear';
  const incidentDetail = attention?.active_incidents.slice(0, 2).map((incident) => incident.title).join(' · ');
  const service = data.service_health.data;
  const product = data.product_value.data;
  const snapshotStale = Boolean(error) || stale;
  const OverallIcon = service ? (snapshotStale ? AlertTriangle : OVERALL_ICON[service.overall]) : CloudOff;

  const overallLabel = (status: OverallStatus): string => {
    switch (status) {
      case 'operational':
        return t`All components operational`;
      case 'degraded':
        return t`Service performance degraded`;
      case 'partial_outage':
        return t`Partial service outage`;
      case 'major_outage':
        return t`Major service outage`;
    }
  };

  const componentStatusLabel = (status: ComponentStatus): string => {
    switch (status) {
      case 'operational':
        return t`Operational`;
      case 'degraded_performance':
        return t`Degraded`;
      case 'partial_outage':
        return t`Partial outage`;
      case 'major_outage':
        return t`Outage`;
    }
  };

  const componentLabel = (key: string, fallback: string): string => {
    switch (key) {
      case 'api':
        return t`API`;
      case 'database':
        return t`Database`;
      case 'sync':
        return t`Background sync`;
      default:
        return fallback;
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-foreground">
            <Trans>Operations</Trans>
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            <Trans>Start with operator action, then use health and usage context to choose the next workflow.</Trans>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-border bg-background p-0.5" aria-label={t`Summary window`}>
            {WINDOWS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setWindow(option)}
                aria-pressed={window === option}
                className={cn(
                  'h-7 rounded-md px-2.5 font-data text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  window === option
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                {option}
              </button>
            ))}
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            <Trans>Refresh</Trans>
          </Button>
        </div>
      </div>

      {error ? (
        <div
          role="status"
          className="flex items-center gap-2 rounded-lg border border-accent-amber/40 bg-accent-amber/5 px-3 py-2 text-xs text-foreground"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 text-accent-amber" />
          <Trans>Refresh failed. Showing the last successful snapshot.</Trans>
        </div>
      ) : null}

      <section aria-labelledby="needs-attention-heading">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
              <Trans>Operator queue</Trans>
            </p>
            <h3 id="needs-attention-heading" className="mt-1 text-base font-semibold text-foreground">
              <Trans>Needs attention</Trans>
            </h3>
          </div>
          <p className="font-data text-[11px] text-muted-foreground">
            <Trans>Snapshot {formatTimestamp(data.generated_at, i18n.locale)}</Trans>
          </p>
        </div>

        <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
          <AttentionRow
            Icon={incidents ? (incidents.total ? ShieldAlert : CheckCircle2) : CloudOff}
            tone={incidentTone}
            title={
              incidents
                ? incidents.total > 0
                  ? t`Active incidents: ${incidents.total}`
                  : t`No active service incidents`
                : t`Incident state unavailable`
            }
            description={
              incidents
                ? incidents.total > 0
                  ? t`Critical: ${incidents.critical}. Major: ${incidents.major}. Minor: ${incidents.minor}.`
                  : t`The public status feed has no unresolved incidents.`
                : localizedReason(data.attention.reason, t`The incident aggregate could not be refreshed.`)
            }
            detail={incidentDetail || undefined}
            to={data.links.incidents}
            action={t`Manage incidents`}
          />
          <AttentionRow
            Icon={feedback ? (feedback.actionable ? MessageSquareWarning : CheckCircle2) : CloudOff}
            tone={feedbackTone}
            title={
              feedback
                ? feedback.actionable > 0
                  ? t`Feedback requiring action: ${feedback.actionable}`
                  : t`Feedback queue is clear`
                : t`Feedback state unavailable`
            }
            description={
              feedback
                ? feedback.actionable > 0
                  ? t`Needs review: ${feedback.needs_review}. Failed: ${feedback.failed}. Critical: ${feedback.critical}. High: ${feedback.high}.`
                  : t`No feedback rows are waiting for review or retry.`
                : localizedReason(data.attention.reason, t`The feedback aggregate could not be refreshed.`)
            }
            to={data.links.feedback}
            action={t`Open feedback`}
          />
          <AttentionRow
            Icon={CloudOff}
            tone="unavailable"
            title={t`Azure alert state unavailable`}
            description={localizedReason(data.azure_alerts.reason, t`Curated alert summaries are not connected yet.`)}
            href={data.links.monitoring_docs}
            action={t`Open alert runbook`}
          />
          <AttentionRow
            Icon={CloudOff}
            tone="unavailable"
            title={t`Systemic sync failures unavailable`}
            description={localizedReason(data.platform_health.reason, t`Platform aggregates are not connected yet.`)}
            href={data.links.monitoring_docs}
            action={t`Open telemetry queries`}
          />
        </div>
        <SectionMeta meta={data.attention} stale={snapshotStale} className="mt-3" />
      </section>

      <div className="grid gap-8 xl:grid-cols-2">
        <section aria-labelledby="service-health-heading">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                {snapshotStale ? <Trans>Last known state</Trans> : <Trans>Live state</Trans>}
              </p>
              <h3 id="service-health-heading" className="mt-1 text-base font-semibold text-foreground">
                <Trans>Service health</Trans>
              </h3>
            </div>
            {service ? (
              <div
                className={cn(
                  'inline-flex items-center gap-1.5 text-xs font-medium',
                  snapshotStale ? 'text-accent-amber' : OVERALL_TONE[service.overall],
                )}
              >
                <OverallIcon className="h-4 w-4" />
                {snapshotStale ? t`Last known: ${overallLabel(service.overall)}` : overallLabel(service.overall)}
              </div>
            ) : null}
          </div>

          {service ? (
            <div className="mt-4 divide-y divide-border border-y border-border">
              {service.components.map((component) => (
                <div key={component.key} className="flex items-center justify-between gap-4 py-3">
                  <div className="flex items-center gap-2.5">
                    {component.key === 'database' ? (
                      <Database className="h-4 w-4 text-muted-foreground" />
                    ) : component.key === 'api' ? (
                      <Server className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <Activity className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="text-sm font-medium text-foreground">{componentLabel(component.key, component.name)}</span>
                  </div>
                  <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                    <span
                      className={cn(
                        'h-2.5 w-2.5 rounded-full',
                        snapshotStale && component.status === 'operational'
                          ? 'bg-accent-amber'
                          : COMPONENT_DOT[component.status],
                      )}
                    />
                    {snapshotStale
                      ? t`Last known: ${componentStatusLabel(component.status)}`
                      : componentStatusLabel(component.status)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
              <Trans>Live component health is unavailable.</Trans>
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <SectionMeta meta={data.service_health} stale={snapshotStale} />
            <a
              href={data.links.public_status}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
            >
              <Trans>Public status</Trans>
              <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
          </div>
        </section>

        <section aria-labelledby="product-value-heading">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                <Trans>Usage proxy</Trans>
              </p>
              <h3 id="product-value-heading" className="mt-1 text-base font-semibold text-foreground">
                <Trans>Product value</Trans>
              </h3>
            </div>
            {product?.directional ? (
              <Badge variant="outline" className="border-accent-cobalt/40 text-accent-cobalt">
                <Trans>Directional</Trans>
              </Badge>
            ) : null}
          </div>

          {product ? (
            <dl className="mt-4 grid grid-cols-2 border-y border-border sm:grid-cols-4">
              {[
                { label: t`DAU`, value: product.dau },
                { label: t`WAU`, value: product.wau },
                { label: t`MAU`, value: product.mau },
                { label: t`Registered`, value: product.registered_users },
              ].map((metric) => (
                <div key={metric.label} className="border-b border-border px-3 py-4 sm:border-b-0 sm:border-r sm:last:border-r-0">
                  <dt className="text-[11px] text-muted-foreground">{metric.label}</dt>
                  <dd className="mt-1 font-data text-lg font-semibold text-foreground">{metric.value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
              <Trans>Usage aggregates are unavailable.</Trans>
            </div>
          )}
          <p className="mt-3 text-xs text-muted-foreground">
            <Trans>Counts use authenticated request activity. Today reach and Coach usefulness stay unavailable until trusted telemetry is separated.</Trans>
          </p>
          <SectionMeta meta={data.product_value} stale={snapshotStale} className="mt-3" />
        </section>
      </div>

      <section aria-labelledby="platform-health-heading" className="border-t border-border pt-7">
        <div className="grid gap-5 lg:grid-cols-[1fr_auto] lg:items-center">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <CloudOff className="h-4 w-4" />
            </div>
            <div>
              <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                <Trans>Azure-backed summary</Trans>
              </p>
              <h3 id="platform-health-heading" className="mt-1 text-base font-semibold text-foreground">
                <Trans>Platform health</Trans>
              </h3>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                {localizedReason(data.platform_health.reason, t`Platform telemetry is unavailable.`)}
              </p>
              <SectionMeta meta={data.platform_health} stale={snapshotStale} className="mt-3" />
            </div>
          </div>
          <div className="flex flex-wrap gap-3 lg:justify-end">
            <a
              href={data.links.monitoring_docs}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-accent-cobalt hover:underline"
            >
              <Trans>Monitoring runbook</Trans>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
            <a
              href={data.links.telemetry_trust_issue}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-accent-cobalt hover:underline"
            >
              <Trans>Telemetry trust boundary</Trans>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
