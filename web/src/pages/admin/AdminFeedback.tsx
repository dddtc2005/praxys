import { useMemo, useState } from 'react';
import { Check, ExternalLink, MessageSquarePlus, RefreshCw, RotateCcw } from 'lucide-react';
import AdminFeedbackImages from '@/components/AdminFeedbackImages';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { apiFetch, extractErrorMessage, useApi } from '@/hooks/useApi';
import { Trans, useLingui } from '@lingui/react/macro';
import type { AdminFeedbackItem, AdminFeedbackSyncResult, FeedbackPriority, FeedbackStatus } from '@/types/api';
import { AdminEmptyState, AdminRouteError, AdminRouteSkeleton } from './AdminRouteState';

type AdminFeedbackFilter = 'active' | 'all' | FeedbackStatus;

const FEEDBACK_STATUS_ORDER: Record<FeedbackStatus, number> = {
  needs_review: 0,
  failed: 1,
  new: 2,
  triaged: 3,
  issue_created: 4,
  resolved: 5,
  rejected: 6,
};

const FEEDBACK_PRIORITY_ORDER: Record<FeedbackPriority, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const FEEDBACK_PRIORITY_CLASS: Record<FeedbackPriority, string> = {
  critical: 'border-destructive/40 text-destructive',
  high: 'border-amber-500/40 text-amber-600',
  medium: 'text-muted-foreground',
  low: 'text-muted-foreground',
};

function feedbackStatusVariant(status: FeedbackStatus): 'default' | 'destructive' | 'outline' | 'secondary' {
  if (status === 'issue_created') return 'default';
  if (status === 'failed') return 'destructive';
  if (status === 'resolved') return 'outline';
  return 'secondary';
}

export default function AdminFeedback() {
  const { t } = useLingui();
  const [feedbackFilter, setFeedbackFilter] = useState<AdminFeedbackFilter>('active');
  const [feedbackBusy, setFeedbackBusy] = useState<number | null>(null);
  const [feedbackSyncing, setFeedbackSyncing] = useState(false);
  const [feedbackSyncMsg, setFeedbackSyncMsg] = useState<string | null>(null);
  const [feedbackActionMsg, setFeedbackActionMsg] = useState<string | null>(null);

  const feedbackUrl = feedbackFilter === 'all' ? '/api/admin/feedback' : `/api/admin/feedback?status=${feedbackFilter}`;
  const { data, loading, error, refetch } = useApi<AdminFeedbackItem[]>(feedbackUrl, { refetchOnMount: 'always' });
  const feedback = useMemo(() => data ?? [], [data]);

  const feedbackStatusLabel = (status: FeedbackStatus): string => {
    switch (status) {
      case 'new':
        return t`New`;
      case 'triaged':
        return t`Triaged`;
      case 'needs_review':
        return t`Needs review`;
      case 'issue_created':
        return t`Issue created`;
      case 'resolved':
        return t`Resolved`;
      case 'failed':
        return t`Failed`;
      case 'rejected':
        return t`Rejected`;
    }
  };

  const feedbackPriorityLabel = (priority: FeedbackPriority): string => {
    switch (priority) {
      case 'critical':
        return t`Critical`;
      case 'high':
        return t`High`;
      case 'medium':
        return t`Medium`;
      case 'low':
        return t`Low`;
    }
  };

  const feedbackKindLabel = (kind: AdminFeedbackItem['kind']): string => {
    switch (kind) {
      case 'bug':
        return t`Bug`;
      case 'feature':
        return t`Feature`;
      case 'other':
        return t`Other`;
    }
  };

  const sortedFeedback = useMemo(
    () =>
      [...feedback].sort((left, right) => {
        const byStatus = FEEDBACK_STATUS_ORDER[left.status] - FEEDBACK_STATUS_ORDER[right.status];
        if (byStatus !== 0) return byStatus;
        if (left.priority && right.priority) {
          return FEEDBACK_PRIORITY_ORDER[left.priority] - FEEDBACK_PRIORITY_ORDER[right.priority];
        }
        if (left.priority) return -1;
        if (right.priority) return 1;
        return 0;
      }),
    [feedback],
  );

  const handleFeedbackAction = async (id: number, action: 'retry' | 'reject' | 'approve') => {
    setFeedbackBusy(id);
    setFeedbackActionMsg(null);
    try {
      const res = await apiFetch(`/api/admin/feedback/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      if (!res.ok) {
        setFeedbackActionMsg(await extractErrorMessage(res, t`Couldn't update feedback.`));
      }
      await refetch();
    } catch {
      setFeedbackActionMsg(t`Network error. Is the server running?`);
    } finally {
      setFeedbackBusy(null);
    }
  };

  const handleFeedbackSync = async () => {
    setFeedbackSyncing(true);
    setFeedbackSyncMsg(null);
    try {
      const res = await apiFetch(`/api/admin/feedback/sync`, {
        method: 'POST',
      });
      if (!res.ok) {
        setFeedbackSyncMsg(await extractErrorMessage(res, t`Sync failed.`));
        return;
      }
      const result: AdminFeedbackSyncResult = await res.json();
      setFeedbackSyncMsg(
        !result.configured
          ? t`GitHub isn't configured. Nothing to sync.`
          : result.updated > 0
            ? t`Updated ${result.updated} of ${result.checked} linked ticket(s).`
            : t`All ${result.checked} linked ticket(s) already up to date.`,
      );
      await refetch();
    } catch {
      setFeedbackSyncMsg(t`Network error. Is the server running?`);
    } finally {
      setFeedbackSyncing(false);
    }
  };

  if (loading) {
    return <AdminRouteSkeleton />;
  }

  if (error) {
    return (
      <AdminRouteError
        title={t`Couldn't load feedback queue`}
        description={t`Retry to load submitted reports and GitHub sync state.`}
        error={error}
        onRetry={refetch}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-foreground">
          <Trans>Feedback triage</Trans>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          <Trans>Review reports, manage screenshots, and sync linked GitHub issues.</Trans>
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <MessageSquarePlus className="h-4 w-4" />
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Trans>User feedback</Trans>
                  {feedback.some((item) => item.status === 'needs_review') ? (
                    <Badge variant="secondary" className="font-data">
                      {feedback.filter((item) => item.status === 'needs_review').length}
                    </Badge>
                  ) : null}
                </CardTitle>
                <CardDescription>
                  <Trans>Bug reports and feature requests submitted from the app.</Trans>
                </CardDescription>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={feedbackFilter} onValueChange={(value) => setFeedbackFilter(value as AdminFeedbackFilter)}>
                <SelectTrigger size="sm" className="w-[160px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">{t`Active`}</SelectItem>
                  <SelectItem value="all">{t`All`}</SelectItem>
                  <SelectItem value="new">{t`New`}</SelectItem>
                  <SelectItem value="needs_review">{t`Needs review`}</SelectItem>
                  <SelectItem value="failed">{t`Failed`}</SelectItem>
                  <SelectItem value="issue_created">{t`Issue created`}</SelectItem>
                  <SelectItem value="resolved">{t`Resolved`}</SelectItem>
                  <SelectItem value="rejected">{t`Rejected`}</SelectItem>
                  <SelectItem value="triaged">{t`Triaged`}</SelectItem>
                </SelectContent>
              </Select>
              <Button type="button" size="sm" variant="outline" disabled={feedbackSyncing} onClick={() => void handleFeedbackSync()}>
                <RefreshCw className={`h-3.5 w-3.5 ${feedbackSyncing ? 'animate-spin' : ''}`} />
                <Trans>Sync from GitHub</Trans>
              </Button>
            </div>
          </div>
          {feedbackSyncMsg ? <p className="mt-2 text-xs text-muted-foreground">{feedbackSyncMsg}</p> : null}
          {feedbackActionMsg ? <p className="mt-2 text-xs text-destructive">{feedbackActionMsg}</p> : null}
        </CardHeader>
        <CardContent>
          {sortedFeedback.length === 0 ? (
            <AdminEmptyState
              title={feedbackFilter === 'active' ? t`No active tickets` : t`No tickets to show`}
              description={
                feedbackFilter === 'active'
                  ? t`Newly triaged work will appear here when admin action is needed.`
                  : t`Try another filter or sync again after new reports arrive.`
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead><Trans>Type</Trans></TableHead>
                  <TableHead><Trans>Status</Trans></TableHead>
                  <TableHead><Trans>Report</Trans></TableHead>
                  <TableHead><Trans>Issue</Trans></TableHead>
                  <TableHead className="text-right"><Trans>Actions</Trans></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedFeedback.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <Badge variant="outline">{feedbackKindLabel(item.kind)}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <Badge
                          variant={feedbackStatusVariant(item.status)}
                          className={item.status === 'resolved' ? 'border-primary/40 text-primary' : undefined}
                        >
                          {feedbackStatusLabel(item.status)}
                        </Badge>
                        {item.priority ? (
                          <Badge variant="outline" className={FEEDBACK_PRIORITY_CLASS[item.priority]}>
                            {feedbackPriorityLabel(item.priority)}
                          </Badge>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-sm">
                      <p className="truncate text-sm" title={item.message}>{item.ai_title || item.message}</p>
                      {item.error ? <p className="text-xs text-destructive">{item.error}</p> : null}
                      {item.image_count > 0 ? (
                        <>
                          {item.image_sensitive ? (
                            <Badge variant="secondary" className="mt-1">
                              <Trans>Screenshot flagged sensitive</Trans>
                            </Badge>
                          ) : null}
                          {item.image_description ? (
                            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={item.image_description}>
                              {item.image_description}
                            </p>
                          ) : null}
                          <AdminFeedbackImages feedbackId={item.id} count={item.image_count} />
                        </>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      {item.github_issue_url ? (
                        <a
                          href={item.github_issue_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                        >
                          <span className="font-data">#{item.github_issue_number}</span>
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        {item.status === 'needs_review' ? (
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            disabled={feedbackBusy === item.id}
                            onClick={() => void handleFeedbackAction(item.id, 'approve')}
                          >
                            <Check className="h-3 w-3" />
                            <Trans>Approve & file</Trans>
                          </Button>
                        ) : null}
                        {item.status !== 'issue_created' && item.status !== 'needs_review' && item.status !== 'resolved' ? (
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            disabled={feedbackBusy === item.id}
                            onClick={() => void handleFeedbackAction(item.id, 'retry')}
                          >
                            <RotateCcw className="h-3 w-3" />
                            <Trans>Retry</Trans>
                          </Button>
                        ) : null}
                        {item.status !== 'rejected' ? (
                          <Button
                            type="button"
                            size="xs"
                            variant="ghost"
                            disabled={feedbackBusy === item.id}
                            onClick={() => void handleFeedbackAction(item.id, 'reject')}
                          >
                            <Trans>Reject</Trans>
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
