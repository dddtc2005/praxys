import { useState } from 'react';
import { AlertTriangle, Plus, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { apiFetch, extractErrorMessage, useApi } from '@/hooks/useApi';
import { Trans, useLingui } from '@lingui/react/macro';
import type { IncidentImpact, IncidentStatus, ServiceIncident } from '@/types/api';
import { AdminEmptyState, AdminRouteError, AdminRouteSkeleton } from './AdminRouteState';

export default function AdminIncidents() {
  const { t } = useLingui();
  const { data, loading, error, refetch } = useApi<ServiceIncident[]>('/api/admin/incidents', { refetchOnMount: 'always' });
  const incidents = data ?? [];
  const [incTitle, setIncTitle] = useState('');
  const [incImpact, setIncImpact] = useState<IncidentImpact>('minor');
  const [incBody, setIncBody] = useState('');
  const [incUpdateBody, setIncUpdateBody] = useState<Record<number, string>>({});
  const [incCreating, setIncCreating] = useState(false);
  const [incidentActionKey, setIncidentActionKey] = useState<string | null>(null);
  const [incError, setIncError] = useState<string | null>(null);

  const impactLabel = (impact: IncidentImpact): string => {
    switch (impact) {
      case 'minor':
        return t`Minor`;
      case 'major':
        return t`Major`;
      case 'critical':
        return t`Critical`;
    }
  };

  const incidentStatusLabel = (status: IncidentStatus): string => {
    switch (status) {
      case 'investigating':
        return t`Investigating`;
      case 'identified':
        return t`Identified`;
      case 'monitoring':
        return t`Monitoring`;
      case 'resolved':
        return t`Resolved`;
    }
  };

  const handleCreateIncident = async () => {
    if (!incTitle.trim()) return;
    setIncCreating(true);
    setIncError(null);
    try {
      const res = await apiFetch(`/api/admin/incidents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: incTitle.trim(), impact: incImpact, body: incBody.trim() }),
      });
      if (!res.ok) {
        setIncError(await extractErrorMessage(res, t`Failed to create incident.`));
        return;
      }
      setIncTitle('');
      setIncBody('');
      setIncImpact('minor');
      await refetch();
    } catch {
      setIncError(t`Network error. Is the server running?`);
    } finally {
      setIncCreating(false);
    }
  };

  const handleIncidentUpdate = async (incident: ServiceIncident, status: IncidentStatus) => {
    const body = (incUpdateBody[incident.id] || '').trim();
    const actionKey = `${incident.id}:${status}`;
    setIncidentActionKey(actionKey);
    setIncError(null);
    try {
      const res = await apiFetch(`/api/admin/incidents/${incident.id}/updates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, body }),
      });
      if (!res.ok) {
        setIncError(await extractErrorMessage(res, t`Failed to update incident.`));
        return;
      }
      setIncUpdateBody((prev) => ({ ...prev, [incident.id]: '' }));
      await refetch();
    } catch {
      setIncError(t`Network error. Is the server running?`);
    } finally {
      setIncidentActionKey(null);
    }
  };

  const handleDeleteIncident = async (id: number) => {
    setIncidentActionKey(`delete:${id}`);
    setIncError(null);
    try {
      const res = await apiFetch(`/api/admin/incidents/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        setIncError(await extractErrorMessage(res, t`Failed to delete incident.`));
        return;
      }
      await refetch();
    } catch {
      setIncError(t`Network error. Is the server running?`);
    } finally {
      setIncidentActionKey(null);
    }
  };

  if (loading) {
    return <AdminRouteSkeleton />;
  }

  if (error) {
    return (
      <AdminRouteError
        title={t`Couldn't load incidents`}
        description={t`Retry to load the public status incidents feed.`}
        error={error}
        onRetry={refetch}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-foreground">
          <Trans>Incident management</Trans>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          <Trans>Open, update, resolve, and remove incidents shown on the public status page.</Trans>
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <div className="flex-1">
              <CardTitle className="text-base">
                <Trans>Service incidents</Trans>
              </CardTitle>
              <CardDescription className="text-xs">
                <Trans>Declare incidents shown on the public</Trans>{' '}
                <a href="/status" target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  <Trans>status page</Trans>
                </a>
                .
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3 rounded-lg border border-dashed border-border p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Trans>New incident</Trans>
            </p>
            <Input
              placeholder={t`Title (e.g. Elevated API latency)`}
              value={incTitle}
              onChange={(event) => setIncTitle(event.target.value)}
            />
            <Input
              placeholder={t`Opening update message (optional)`}
              value={incBody}
              onChange={(event) => setIncBody(event.target.value)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={incImpact}
                onChange={(event) => setIncImpact(event.target.value as IncidentImpact)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="minor">{t`Minor`}</option>
                <option value="major">{t`Major`}</option>
                <option value="critical">{t`Critical`}</option>
              </select>
              <Button type="button" size="sm" onClick={() => void handleCreateIncident()} disabled={incCreating || !incTitle.trim()}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {incCreating ? <Trans>Creating…</Trans> : <Trans>Open incident</Trans>}
              </Button>
            </div>
            {incError ? <p className="text-xs text-destructive">{incError}</p> : null}
          </div>

          {incidents.length === 0 ? (
            <AdminEmptyState
              title={t`No incidents yet`}
              description={t`Open an incident here when you need to communicate a live service issue.`}
            />
          ) : (
            <div className="space-y-2">
              {incidents.map((incident) => (
                <div
                  key={incident.id}
                  className={`rounded-lg border p-3 text-sm ${incident.status === 'resolved' ? 'opacity-60' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="shrink-0 text-xs">
                      {impactLabel(incident.impact)}
                    </Badge>
                    <span className="flex-1 truncate font-medium">{incident.title}</span>
                    <Badge variant="secondary" className="shrink-0 text-xs">
                      {incidentStatusLabel(incident.status)}
                    </Badge>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                      onClick={() => void handleDeleteIncident(incident.id)}
                      disabled={incidentActionKey === `delete:${incident.id}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  {incident.status !== 'resolved' ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Input
                        placeholder={t`Update message (optional)`}
                        value={incUpdateBody[incident.id] || ''}
                        onChange={(event) =>
                          setIncUpdateBody((prev) => ({ ...prev, [incident.id]: event.target.value }))
                        }
                        className="h-8 min-w-[12rem] flex-1"
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-8"
                        onClick={() => void handleIncidentUpdate(incident, 'identified')}
                        disabled={incidentActionKey === `${incident.id}:identified`}
                      >
                        <Trans>Identified</Trans>
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-8"
                        onClick={() => void handleIncidentUpdate(incident, 'monitoring')}
                        disabled={incidentActionKey === `${incident.id}:monitoring`}
                      >
                        <Trans>Monitoring</Trans>
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        className="h-8"
                        onClick={() => void handleIncidentUpdate(incident, 'resolved')}
                        disabled={incidentActionKey === `${incident.id}:resolved`}
                      >
                        <Trans>Resolve</Trans>
                      </Button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
