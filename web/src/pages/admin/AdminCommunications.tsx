import { useState } from 'react';
import { Languages, Megaphone, Plus, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { apiFetch, extractErrorMessage, useApi } from '@/hooks/useApi';
import { Trans, useLingui } from '@lingui/react/macro';
import type { SystemAnnouncement } from '@/types/api';
import { AdminEmptyState, AdminRouteError, AdminRouteSkeleton } from './AdminRouteState';

export default function AdminCommunications() {
  const { t } = useLingui();
  const { data, loading, error, refetch } = useApi<SystemAnnouncement[]>('/api/admin/announcements', { refetchOnMount: 'always' });
  const announcements = data ?? [];
  const [newTitle, setNewTitle] = useState('');
  const [newBody, setNewBody] = useState('');
  const [newType, setNewType] = useState<'info' | 'warning' | 'success'>('info');
  const [newLinkText, setNewLinkText] = useState('');
  const [newLinkUrl, setNewLinkUrl] = useState('');
  const [newTitleZh, setNewTitleZh] = useState('');
  const [newBodyZh, setNewBodyZh] = useState('');
  const [newLinkTextZh, setNewLinkTextZh] = useState('');
  const [creating, setCreating] = useState(false);
  const [busyAnnouncementId, setBusyAnnouncementId] = useState<number | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const announcementTypeLabel = (type: SystemAnnouncement['type']): string => {
    switch (type) {
      case 'info':
        return t`Info`;
      case 'warning':
        return t`Warning`;
      case 'success':
        return t`Success`;
    }
  };

  const handleCreateAnnouncement = async () => {
    if (!newTitle.trim()) return;
    setCreating(true);
    setCreateError(null);
    const zh: Record<string, string> = {};
    if (newTitleZh.trim()) zh.title = newTitleZh.trim();
    if (newBodyZh.trim()) zh.body = newBodyZh.trim();
    if (newLinkTextZh.trim()) zh.link_text = newLinkTextZh.trim();
    const translations = Object.keys(zh).length ? { zh } : undefined;

    try {
      const res = await apiFetch(`/api/admin/announcements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: newTitle.trim(),
          body: newBody.trim(),
          type: newType,
          link_text: newLinkText.trim() || null,
          link_url: newLinkUrl.trim() || null,
          translations,
        }),
      });
      if (!res.ok) {
        setCreateError(await extractErrorMessage(res, t`Failed to create announcement.`));
        return;
      }
      setNewTitle('');
      setNewBody('');
      setNewType('info');
      setNewLinkText('');
      setNewLinkUrl('');
      setNewTitleZh('');
      setNewBodyZh('');
      setNewLinkTextZh('');
      await refetch();
    } catch {
      setCreateError(t`Network error. Is the server running?`);
    } finally {
      setCreating(false);
    }
  };

  const handleToggleAnnouncement = async (announcement: SystemAnnouncement) => {
    setBusyAnnouncementId(announcement.id);
    setActionError(null);
    try {
      const res = await apiFetch(`/api/admin/announcements/${announcement.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !announcement.is_active }),
      });
      if (!res.ok) {
        setActionError(await extractErrorMessage(res, t`Failed to update announcement.`));
        return;
      }
      await refetch();
    } catch {
      setActionError(t`Network error. Is the server running?`);
    } finally {
      setBusyAnnouncementId(null);
    }
  };

  const handleDeleteAnnouncement = async (id: number) => {
    setBusyAnnouncementId(id);
    setActionError(null);
    try {
      const res = await apiFetch(`/api/admin/announcements/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        setActionError(await extractErrorMessage(res, t`Failed to delete announcement.`));
        return;
      }
      await refetch();
    } catch {
      setActionError(t`Network error. Is the server running?`);
    } finally {
      setBusyAnnouncementId(null);
    }
  };

  if (loading) {
    return <AdminRouteSkeleton />;
  }

  if (error) {
    return (
      <AdminRouteError
        title={t`Couldn't load announcements`}
        description={t`Retry to load public communication banners.`}
        error={error}
        onRetry={refetch}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-foreground">
          <Trans>Communications</Trans>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          <Trans>Create and manage dismissible banners shown to all users.</Trans>
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Megaphone className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-base">
                <Trans>System announcements</Trans>
              </CardTitle>
              <CardDescription className="text-xs">
                <Trans>Bilingual announcement banners for product-wide communication.</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3 rounded-lg border border-dashed border-border p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Trans>New announcement</Trans>
            </p>

            <div className="space-y-2">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                <Trans>Default (English)</Trans>
              </p>
              <Input placeholder={t`Title`} value={newTitle} onChange={(event) => setNewTitle(event.target.value)} />
              <Input placeholder={t`Body (optional)`} value={newBody} onChange={(event) => setNewBody(event.target.value)} />
              <Input
                placeholder={t`Link text (optional)`}
                value={newLinkText}
                onChange={(event) => setNewLinkText(event.target.value)}
              />
            </div>

            <div className="space-y-2">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                <Trans>Chinese</Trans> <span className="normal-case font-normal opacity-70">(<Trans>optional</Trans>)</span>
              </p>
              <Input placeholder={t`Title`} value={newTitleZh} onChange={(event) => setNewTitleZh(event.target.value)} />
              <Input placeholder={t`Body (optional)`} value={newBodyZh} onChange={(event) => setNewBodyZh(event.target.value)} />
              <Input
                placeholder={t`Link text (optional)`}
                value={newLinkTextZh}
                onChange={(event) => setNewLinkTextZh(event.target.value)}
              />
            </div>

            <div className="flex flex-wrap gap-2">
              <select
                value={newType}
                onChange={(event) => setNewType(event.target.value as 'info' | 'warning' | 'success')}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="info">{t`Info`}</option>
                <option value="warning">{t`Warning`}</option>
                <option value="success">{t`Success`}</option>
              </select>
              <Input
                placeholder={t`Link URL (optional)`}
                value={newLinkUrl}
                onChange={(event) => setNewLinkUrl(event.target.value)}
                className="min-w-[14rem] flex-1"
              />
            </div>

            {createError ? <p className="text-xs text-destructive">{createError}</p> : null}

            <Button type="button" size="sm" onClick={() => void handleCreateAnnouncement()} disabled={creating || !newTitle.trim()}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {creating ? <Trans>Creating…</Trans> : <Trans>Create</Trans>}
            </Button>
          </div>

          {actionError ? <p className="text-xs text-destructive">{actionError}</p> : null}

          {announcements.length === 0 ? (
            <AdminEmptyState
              title={t`No announcements yet`}
              description={t`Publish a banner above to communicate maintenance windows, launches, or onboarding news.`}
            />
          ) : (
            <div className="space-y-2">
              {announcements.map((announcement) => (
                <div
                  key={announcement.id}
                  className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${announcement.is_active ? '' : 'opacity-50'}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="shrink-0 text-xs">
                        {announcementTypeLabel(announcement.type)}
                      </Badge>
                      {announcement.translations?.zh && Object.keys(announcement.translations.zh).length > 0 ? (
                        <Badge variant="outline" className="shrink-0 gap-1 text-[10px] text-muted-foreground">
                          <Languages className="h-3 w-3" />
                          <Trans>Chinese</Trans>
                        </Badge>
                      ) : null}
                      <span className="truncate font-medium">{announcement.title}</span>
                    </div>
                    {announcement.body ? <p className="mt-0.5 truncate text-xs text-muted-foreground">{announcement.body}</p> : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => void handleToggleAnnouncement(announcement)}
                      disabled={busyAnnouncementId === announcement.id}
                    >
                      {announcement.is_active ? <Trans>Deactivate</Trans> : <Trans>Activate</Trans>}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                      onClick={() => void handleDeleteAnnouncement(announcement.id)}
                      disabled={busyAnnouncementId === announcement.id}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
