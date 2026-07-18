import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Eye,
  Mail,
  Plus,
  Send,
  ShieldCheck,
  Ticket,
  Trash2,
  UserPlus,
  Users,
} from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { apiFetch, extractErrorMessage, useApi } from '@/hooks/useApi';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Trans, useLingui } from '@lingui/react/macro';
import type {
  AdminConfig,
  AdminInvitationCreateResponse,
  AdminInvitationsResponse,
  AdminUserInfo,
  AdminUsersResponse,
  AdminWaitlistResponse,
  WaitlistInviteResult,
  WaitlistSignupItem,
} from '@/types/api';
import { AdminEmptyState, AdminRouteError } from './AdminRouteState';

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : '—';
}

function gaugePct(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((value / total) * 100)));
}

function AdminUsersSectionSkeleton() {
  return (
    <div aria-busy="true" className="space-y-3 rounded-xl border border-border bg-card p-5">
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-4 w-64 max-w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export default function AdminUsers() {
  const { email: currentEmail } = useAuth();
  const { t } = useLingui();
  const {
    data: config,
    loading: configLoading,
    error: configError,
    refetch: refetchConfig,
  } = useApi<AdminConfig>('/api/admin/config', { refetchOnMount: 'always' });
  const {
    data: usersResponse,
    loading: usersLoading,
    error: usersError,
    refetch: refetchUsers,
  } = useApi<AdminUsersResponse>('/api/admin/users', { refetchOnMount: 'always' });
  const {
    data: invitationsResponse,
    loading: invitationsLoading,
    error: invitationsError,
    refetch: refetchInvitations,
  } = useApi<AdminInvitationsResponse>('/api/admin/invitations', { refetchOnMount: 'always' });
  const {
    data: waitlistResponse,
    loading: waitlistLoading,
    error: waitlistError,
    refetch: refetchWaitlist,
  } = useApi<AdminWaitlistResponse>('/api/admin/waitlist', { refetchOnMount: 'always' });

  const [inviteNote, setInviteNote] = useState('');
  const [newCode, setNewCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const [maxUsersDraft, setMaxUsersDraft] = useState<string | null>(null);
  const [configMsg, setConfigMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [invitationMsg, setInvitationMsg] = useState<string | null>(null);
  const [membershipMsg, setMembershipMsg] = useState<string | null>(null);
  const [waitlistMsg, setWaitlistMsg] = useState<string | null>(null);
  const [inviteResults, setInviteResults] = useState<Record<number, WaitlistInviteResult>>({});
  const [deleteUser, setDeleteUser] = useState<AdminUserInfo | null>(null);
  const [roleChangeUser, setRoleChangeUser] = useState<AdminUserInfo | null>(null);
  const [demoEmail, setDemoEmail] = useState('');
  const [demoPassword, setDemoPassword] = useState('');
  const [demoError, setDemoError] = useState<string | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);
  const [generatingInvite, setGeneratingInvite] = useState(false);
  const [invitationBusyId, setInvitationBusyId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [changingRole, setChangingRole] = useState(false);
  const [creatingDemo, setCreatingDemo] = useState(false);
  const [invitingId, setInvitingId] = useState<number | null>(null);

  const maxUsersInput = maxUsersDraft ?? (config ? String(config.registration.max_users) : '');

  const users = usersResponse?.users ?? [];
  const invitations = invitationsResponse?.invitations ?? [];
  const waitlist = waitlistResponse?.signups ?? [];

  const activityGauge = useMemo(() => {
    if (!config) return [];
    const totalUsers = config.activity.total_users;
    return [
      { key: 'dau', label: t`DAU`, value: config.activity.dau, totalUsers, accent: 'bg-primary' },
      { key: 'wau', label: t`WAU`, value: config.activity.wau, totalUsers, accent: 'bg-primary/80' },
      { key: 'mau', label: t`MAU`, value: config.activity.mau, totalUsers, accent: 'bg-primary/60' },
    ];
  }, [config, t]);

  const copyCode = (code: string) => {
    void navigator.clipboard?.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const copyInviteCode = (code: string) => {
    void navigator.clipboard?.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 1500);
  };

  const patchConfig = async (payload: { registration_open?: boolean; registration_max_users?: number }) => {
    setSavingConfig(true);
    setConfigMsg(null);
    try {
      const res = await apiFetch(`/api/admin/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error(await extractErrorMessage(res, t`Couldn't save changes.`));
      }
      await refetchConfig();
      setConfigMsg({ ok: true, text: t`Saved` });
    } catch (err) {
      await refetchConfig();
      setConfigMsg({
        ok: false,
        text: err instanceof Error ? err.message : t`Couldn't save changes.`,
      });
    } finally {
      if (payload.registration_max_users !== undefined) {
        setMaxUsersDraft(null);
      }
      setSavingConfig(false);
    }
  };

  const handleToggleRegistration = () => {
    if (!config) return;
    void patchConfig({ registration_open: !config.registration.flag_enabled });
  };

  const handleSaveMaxUsers = () => {
    const nextValue = Number.parseInt(maxUsersInput, 10);
    if (!Number.isFinite(nextValue) || nextValue < 0) return;
    void patchConfig({ registration_max_users: nextValue });
  };

  const handleGenerateInvite = async () => {
    setGeneratingInvite(true);
    setInvitationMsg(null);
    try {
      const res = await apiFetch(`/api/admin/invitations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: inviteNote }),
      });
      if (!res.ok) {
        setInvitationMsg(await extractErrorMessage(res, t`Failed to generate invitation code.`));
        return;
      }
      const data: AdminInvitationCreateResponse = await res.json();
      setNewCode(data.code);
      setInviteNote('');
      await Promise.all([refetchConfig(), refetchInvitations()]);
    } catch {
      setInvitationMsg(t`Network error. Is the server running?`);
    } finally {
      setGeneratingInvite(false);
    }
  };

  const handleRevokeInvite = async (id: number) => {
    setInvitationBusyId(id);
    setInvitationMsg(null);
    try {
      const res = await apiFetch(`/api/admin/invitations/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        setInvitationMsg(await extractErrorMessage(res, t`Failed to revoke invitation code.`));
        return;
      }
      await Promise.all([refetchConfig(), refetchInvitations()]);
    } catch {
      setInvitationMsg(t`Network error. Is the server running?`);
    } finally {
      setInvitationBusyId(null);
    }
  };

  const handleDeleteUser = async () => {
    if (!deleteUser) return;
    setDeleting(true);
    setMembershipMsg(null);
    try {
      const res = await apiFetch(`/api/admin/users/${deleteUser.id}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        setMembershipMsg(await extractErrorMessage(res, t`Failed to delete user.`));
        return;
      }
      setDeleteUser(null);
      await Promise.all([refetchConfig(), refetchUsers(), refetchInvitations(), refetchWaitlist()]);
    } catch {
      setMembershipMsg(t`Network error. Is the server running?`);
    } finally {
      setDeleting(false);
    }
  };

  const handleConfirmRoleChange = async () => {
    if (!roleChangeUser) return;
    setChangingRole(true);
    setMembershipMsg(null);
    try {
      const res = await apiFetch(`/api/admin/users/${roleChangeUser.id}/role`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_superuser: !roleChangeUser.is_superuser }),
      });
      if (!res.ok) {
        setMembershipMsg(await extractErrorMessage(res, t`Failed to update user role.`));
        return;
      }
      setRoleChangeUser(null);
      await refetchUsers();
    } catch {
      setMembershipMsg(t`Network error. Is the server running?`);
    } finally {
      setChangingRole(false);
    }
  };

  const handleInviteWaitlist = async (row: WaitlistSignupItem) => {
    setInvitingId(row.id);
    setWaitlistMsg(null);
    try {
      const res = await apiFetch(`/api/admin/waitlist/${row.id}/invite`, {
        method: 'POST',
      });
      if (!res.ok) {
        setWaitlistMsg(await extractErrorMessage(res, t`Failed to send invitation.`));
        return;
      }
      const result: WaitlistInviteResult = await res.json();
      setInviteResults((prev) => ({ ...prev, [row.id]: result }));
      await Promise.all([refetchConfig(), refetchInvitations(), refetchWaitlist()]);
    } catch {
      setWaitlistMsg(t`Network error. Is the server running?`);
    } finally {
      setInvitingId(null);
    }
  };

  const handleCreateDemo = async () => {
    if (!demoEmail.trim() || !demoPassword.trim()) return;
    setCreatingDemo(true);
    setDemoError(null);
    try {
      const res = await apiFetch(`/api/admin/demo-accounts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: demoEmail, password: demoPassword }),
      });
      if (!res.ok) {
        setDemoError(await extractErrorMessage(res, t`Failed to create demo account.`));
        return;
      }
      setDemoEmail('');
      setDemoPassword('');
      await Promise.all([refetchConfig(), refetchUsers()]);
    } catch {
      setDemoError(t`Network error. Is the server running?`);
    } finally {
      setCreatingDemo(false);
    }
  };


  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-foreground">
          <Trans>Users and access</Trans>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          <Trans>Manage seats, roles, invitations, and waitlist onboarding.</Trans>
        </p>
      </div>

      {(configError || usersError || invitationsError || waitlistError) ? (
        <div className="space-y-3">
          {configError ? (
            <AdminRouteError
              title={t`Registration settings unavailable`}
              description={t`This section is unavailable. Other management workflows remain available.`}
              error={configError}
              onRetry={refetchConfig}
            />
          ) : null}
          {usersError ? (
            <AdminRouteError
              title={t`Users unavailable`}
              description={t`This section is unavailable. Other management workflows remain available.`}
              error={usersError}
              onRetry={refetchUsers}
            />
          ) : null}
          {invitationsError ? (
            <AdminRouteError
              title={t`Invitation codes unavailable`}
              description={t`This section is unavailable. Other management workflows remain available.`}
              error={invitationsError}
              onRetry={refetchInvitations}
            />
          ) : null}
          {waitlistError ? (
            <AdminRouteError
              title={t`Waitlist unavailable`}
              description={t`This section is unavailable. Other management workflows remain available.`}
              error={waitlistError}
              onRetry={refetchWaitlist}
            />
          ) : null}
        </div>
      ) : null}

      {configLoading && !config ? (
        <AdminUsersSectionSkeleton />
      ) : config ? (
        <>
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <UserPlus className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">
                <Trans>Registration</Trans>
                {config.registration.registration_open ? (
                  <Badge className="ml-2 border-primary/30 bg-primary/15 font-data text-primary">
                    <Trans>Open</Trans>
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="ml-2">
                    {config.registration.cap_reached ? <Trans>Closed · cap reached</Trans> : <Trans>Closed</Trans>}
                  </Badge>
                )}
              </CardTitle>
              <CardDescription className="text-xs">
                <Trans>Control self-registration and the committed-seat cap.</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {!config.email_configured ? (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                <Trans>
                  Email is not configured. Open sign-ups will not be email-verified, and invitation codes can't be
                  emailed automatically. Copy them manually until SMTP is configured.
                </Trans>
              </span>
            </div>
          ) : null}

          <div className="flex flex-wrap items-end gap-6">
            <div>
              <p className="mb-1 text-xs text-muted-foreground">
                <Trans>Self-registration</Trans>
              </p>
              <Button
                type="button"
                variant={config.registration.flag_enabled ? 'default' : 'outline'}
                size="sm"
                onClick={handleToggleRegistration}
                disabled={savingConfig}
              >
                {config.registration.flag_enabled ? <Trans>Enabled. Click to close</Trans> : <Trans>Disabled. Click to open</Trans>}
              </Button>
              {configMsg ? (
                <p className={`mt-1.5 text-xs ${configMsg.ok ? 'text-primary' : 'text-destructive'}`}>{configMsg.text}</p>
              ) : null}
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted-foreground">
                <Trans>Seat cap</Trans>
              </label>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={0}
                  value={maxUsersInput}
                  onChange={(event) => setMaxUsersDraft(event.target.value)}
                  className="h-8 w-24 font-data text-xs"
                />
                <Button type="button" size="sm" variant="outline" onClick={handleSaveMaxUsers} disabled={savingConfig}>
                  <Trans>Save</Trans>
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border px-3 py-2">
              <p className="text-[11px] text-muted-foreground">
                <Trans>Registered</Trans>
              </p>
              <p className="font-data text-lg font-semibold text-foreground">{config.registration.registered_users}</p>
            </div>
            <div className="rounded-lg border border-border px-3 py-2">
              <p className="text-[11px] text-muted-foreground">
                <Trans>Outstanding codes</Trans>
              </p>
              <p className="font-data text-lg font-semibold text-foreground">{config.registration.outstanding_invitations}</p>
            </div>
            <div
              className={`rounded-lg border px-3 py-2 ${config.registration.cap_reached ? 'border-amber-500/40 bg-amber-500/5' : 'border-border'}`}
            >
              <p className="text-[11px] text-muted-foreground">
                <Trans>Committed / cap</Trans>
              </p>
              <p className="font-data text-lg font-semibold text-foreground">
                {config.registration.committed_seats} / {config.registration.max_users}
              </p>
            </div>
            <div className="rounded-lg border border-border px-3 py-2">
              <p className="text-[11px] text-muted-foreground">
                <Trans>Remaining</Trans>
              </p>
              <p className="font-data text-lg font-semibold text-foreground">{config.registration.remaining}</p>
            </div>
          </div>

          <p className="text-[11px] text-muted-foreground">
            <Trans>
              Sending an invitation reserves a seat. Self-registration closes automatically at the cap, so review
              readiness before raising it.
            </Trans>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">
                <Trans>Activity gauge</Trans>
              </CardTitle>
              <CardDescription className="text-xs">
                <Trans>Recent usage across the registered base.</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
            <span className="text-xs text-muted-foreground">
              <Trans>Total users tracked</Trans>
            </span>
            <span className="font-data text-sm font-semibold text-foreground">{config.activity.total_users}</span>
          </div>
          <div className="space-y-3">
            {activityGauge.map((item) => (
              <div key={item.key} className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{item.label}</span>
                  <span className="font-data text-foreground">
                    {item.value} / {item.totalUsers}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-muted">
                  <div
                    className={`h-2 rounded-full ${item.accent}`}
                    style={{ width: `${gaugePct(item.value, item.totalUsers)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

        </>
      ) : configError ? null : (
        <AdminEmptyState
          title={t`No admin configuration found`}
          description={t`Reload the page or verify the management endpoints are available.`}
          action={
            <Button type="button" variant="outline" size="sm" onClick={() => void refetchConfig()}>
              <Trans>Retry</Trans>
            </Button>
          }
        />
      )}

      {usersLoading && !usersResponse ? (
        <AdminUsersSectionSkeleton />
      ) : usersError && !usersResponse ? null : (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Users className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">
                <Trans>Users</Trans>{' '}
                <Badge variant="secondary" className="ml-2 font-data">
                  {users.length}
                </Badge>
              </CardTitle>
              <CardDescription className="text-xs">
                <Trans>Registered accounts.</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {membershipMsg ? <p className="mb-3 text-xs text-destructive">{membershipMsg}</p> : null}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead><Trans>Email</Trans></TableHead>
                <TableHead><Trans>Role</Trans></TableHead>
                <TableHead><Trans>Registered</Trans></TableHead>
                <TableHead className="w-32 text-right"><Trans>Actions</Trans></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-sm text-muted-foreground">
                    <Trans>No users found.</Trans>
                  </TableCell>
                </TableRow>
              ) : (
                users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">
                      {user.email}
                      {user.email === currentEmail ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          (<Trans>you</Trans>)
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      {user.is_demo ? (
                        <div>
                          <Badge variant="outline" className="border-amber-500/40 text-xs text-amber-600">
                            <Trans>Demo</Trans>
                          </Badge>
                          {user.demo_of_email ? (
                            <span className="ml-1.5 text-[10px] text-muted-foreground">
                              <Trans>mirrors {user.demo_of_email}</Trans>
                            </span>
                          ) : null}
                        </div>
                      ) : user.is_superuser ? (
                        <Badge className="text-xs">
                          <ShieldCheck className="mr-1 h-3 w-3" />
                          <Trans>Admin</Trans>
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-xs">
                          <Trans>User</Trans>
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="font-data text-xs text-muted-foreground">{formatDate(user.created_at)}</TableCell>
                    <TableCell className="text-right">
                      {user.email !== currentEmail ? (
                        <div className="flex items-center justify-end gap-1">
                          {!user.is_demo ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs text-muted-foreground hover:text-foreground"
                              onClick={() => setRoleChangeUser(user)}
                              title={user.is_superuser ? t`Demote to User` : t`Promote to Admin`}
                            >
                              {user.is_superuser ? (
                                <>
                                  <ChevronDown className="mr-1 h-3 w-3" />
                                  <Trans>Demote</Trans>
                                </>
                              ) : (
                                <>
                                  <ChevronUp className="mr-1 h-3 w-3" />
                                  <Trans>Promote</Trans>
                                </>
                              )}
                            </Button>
                          ) : null}
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs text-muted-foreground hover:text-destructive"
                            onClick={() => setDeleteUser(user)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      )}

      {invitationsLoading && !invitationsResponse ? (
        <AdminUsersSectionSkeleton />
      ) : invitationsError && !invitationsResponse ? null : (
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Ticket className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground">
                  <Trans>Invitation codes</Trans>{' '}
                  <Badge variant="secondary" className="ml-2 font-data">
                    {invitations.length}
                  </Badge>
                </CardTitle>
                <CardDescription className="text-xs">
                  <Trans>One-time codes for new user registration.</Trans>
                </CardDescription>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Input
                placeholder={t`Note (optional)`}
                value={inviteNote}
                onChange={(event) => setInviteNote(event.target.value)}
                className="h-8 w-40 text-xs"
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    void handleGenerateInvite();
                  }
                }}
              />
              <Button type="button" size="sm" onClick={() => void handleGenerateInvite()} disabled={generatingInvite}>
                <Plus className="mr-1 h-3 w-3" />
                {generatingInvite ? <Trans>Generating…</Trans> : <Trans>Generate</Trans>}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {invitationMsg ? <p className="mb-3 text-xs text-destructive">{invitationMsg}</p> : null}
          {newCode ? (
            <div className="mb-4 flex items-center justify-between rounded-lg border border-primary/30 bg-primary/10 px-4 py-3">
              <div>
                <p className="text-xs text-muted-foreground">
                  <Trans>New invitation code:</Trans>
                </p>
                <p className="font-data text-lg font-bold tracking-wider text-primary">{newCode}</p>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => copyCode(newCode)}>
                {copied ? <Check className="h-4 w-4 text-primary" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          ) : null}

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead><Trans>Code</Trans></TableHead>
                <TableHead><Trans>Note</Trans></TableHead>
                <TableHead><Trans>Status</Trans></TableHead>
                <TableHead><Trans>Used by</Trans></TableHead>
                <TableHead><Trans>Created</Trans></TableHead>
                <TableHead className="w-24 text-right"><Trans>Actions</Trans></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-sm text-muted-foreground">
                    <Trans>No invitation codes yet. Generate one to invite a user.</Trans>
                  </TableCell>
                </TableRow>
              ) : (
                invitations.map((invitation) => (
                  <TableRow key={invitation.id} className={!invitation.is_active || invitation.used_by ? 'opacity-50' : ''}>
                    <TableCell>
                      <button
                        type="button"
                        className="font-data text-sm tracking-wider transition-colors hover:text-primary"
                        onClick={() => copyInviteCode(invitation.code)}
                        title={t`Click to copy`}
                      >
                        {invitation.code}
                      </button>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{invitation.note || '—'}</TableCell>
                    <TableCell>
                      {invitation.used_by ? (
                        <Badge variant="secondary" className="text-[10px]">
                          <Trans>Used</Trans>
                        </Badge>
                      ) : invitation.is_active ? (
                        <Badge className="border-primary/30 bg-primary/20 text-[10px] text-primary">
                          <Trans>Available</Trans>
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-[10px] text-destructive">
                          <Trans>Revoked</Trans>
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{invitation.used_by || '—'}</TableCell>
                    <TableCell className="font-data text-xs text-muted-foreground">{formatDate(invitation.created_at)}</TableCell>
                    <TableCell className="text-right">
                      {invitation.is_active && !invitation.used_by ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-muted-foreground hover:text-destructive"
                          onClick={() => void handleRevokeInvite(invitation.id)}
                          disabled={invitationBusyId === invitation.id}
                        >
                          <Trans>Revoke</Trans>
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      )}

      {waitlistLoading && !waitlistResponse ? (
        <AdminUsersSectionSkeleton />
      ) : waitlistError && !waitlistResponse ? null : (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Mail className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">
                <Trans>Waitlist</Trans>{' '}
                <Badge variant="secondary" className="ml-2 font-data">
                  {waitlist.length}
                </Badge>
              </CardTitle>
              <CardDescription className="text-xs">
                <Trans>Prospective users: generate invitation codes and follow up by email.</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {waitlistMsg ? <p className="mb-3 text-xs text-destructive">{waitlistMsg}</p> : null}
          {Object.keys(inviteResults).length > 0 ? (
            <div className="mb-4 space-y-2">
              {Object.entries(inviteResults).map(([id, result]) => {
                const inviteSubject = t`Your Praxys invitation`;
                const inviteBody = t`Your Praxys invitation code: ${result.code}

Finish registering here: ${result.invite_url}`;
                return (
                  <div key={id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-xs">
                    <span className="text-muted-foreground">
                      {result.sent ? (
                        <Trans>Invitation emailed to {result.email} · code {result.code}</Trans>
                      ) : (
                        <Trans>Code {result.code} created for {result.email}. Email not sent. Copy it or use the link.</Trans>
                      )}
                    </span>
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 font-data text-muted-foreground hover:text-foreground"
                        onClick={() => copyInviteCode(result.code)}
                      >
                        {copiedCode === result.code ? <Check className="h-3 w-3 text-primary" /> : <Copy className="h-3 w-3" />}
                        <Trans>Copy code</Trans>
                      </button>
                      {!result.sent ? (
                        <a
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                          href={`mailto:${result.email}?subject=${encodeURIComponent(inviteSubject)}&body=${encodeURIComponent(inviteBody)}`}
                        >
                          <Mail className="h-3 w-3" />
                          <Trans>Email link</Trans>
                        </a>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead><Trans>Email</Trans></TableHead>
                <TableHead><Trans>Goal</Trans></TableHead>
                <TableHead><Trans>Joined</Trans></TableHead>
                <TableHead><Trans>Status</Trans></TableHead>
                <TableHead className="text-right"><Trans>Action</Trans></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {waitlist.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-6 text-center text-sm text-muted-foreground">
                    <Trans>No waitlist signups yet.</Trans>
                  </TableCell>
                </TableRow>
              ) : (
                waitlist.map((signup) => {
                  const codeButton = signup.invitation_code ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 font-data text-xs text-muted-foreground hover:text-foreground"
                      onClick={() => copyInviteCode(signup.invitation_code!)}
                      title={t`Copy code`}
                    >
                      {signup.invitation_code}
                      {copiedCode === signup.invitation_code ? (
                        <Check className="h-3 w-3 text-primary" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </button>
                  ) : null;

                  return (
                    <TableRow key={signup.id}>
                      <TableCell className="font-medium">{signup.email}</TableCell>
                      <TableCell className="max-w-[16rem] truncate text-xs text-muted-foreground">{signup.note || '—'}</TableCell>
                      <TableCell className="font-data text-xs text-muted-foreground">{formatDate(signup.created_at)}</TableCell>
                      <TableCell>
                        {signup.registered ? (
                          <div className="flex items-center gap-1.5">
                            <Badge className="border-transparent bg-primary text-primary-foreground">
                              <Trans>Joined</Trans>
                            </Badge>
                            {codeButton}
                          </div>
                        ) : signup.invited_at ? (
                          <div className="flex items-center gap-1.5">
                            <Badge className="border-primary/30 bg-primary/15 text-primary">
                              <Trans>Invited</Trans>
                            </Badge>
                            {codeButton}
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {signup.registered ? (
                          <span className="text-xs text-muted-foreground">—</span>
                        ) : (
                          <Button
                            type="button"
                            size="sm"
                            variant={signup.invited_at ? 'outline' : 'default'}
                            onClick={() => void handleInviteWaitlist(signup)}
                            disabled={invitingId === signup.id}
                          >
                            <Send className="mr-1 h-3 w-3" />
                            {invitingId === signup.id ? (
                              <Trans>Sending…</Trans>
                            ) : signup.invited_at ? (
                              <Trans>Re-invite</Trans>
                            ) : (
                              <Trans>Invite</Trans>
                            )}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      )}

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600">
              <Eye className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">
                <Trans>Demo accounts</Trans>
              </CardTitle>
              <CardDescription className="text-xs">
                <Trans>Read-only accounts that mirror your dashboard data.</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-end">
            <div className="flex-1 space-y-1">
              <label className="text-xs text-muted-foreground">
                <Trans>Email</Trans>
              </label>
              <Input
                type="email"
                placeholder={t`demo@example.com`}
                value={demoEmail}
                onChange={(event) => setDemoEmail(event.target.value)}
                className="h-8 text-xs"
              />
            </div>
            <div className="flex-1 space-y-1">
              <label className="text-xs text-muted-foreground">
                <Trans>Password</Trans>
              </label>
              <Input
                type="password"
                placeholder={t`demo-password`}
                value={demoPassword}
                onChange={(event) => setDemoPassword(event.target.value)}
                className="h-8 font-data text-xs"
              />
            </div>
            <Button
              type="button"
              size="sm"
              onClick={() => void handleCreateDemo()}
              disabled={creatingDemo || !demoEmail.trim() || !demoPassword.trim()}
            >
              <Plus className="mr-1 h-3 w-3" />
              {creatingDemo ? <Trans>Creating…</Trans> : <Trans>Create</Trans>}
            </Button>
          </div>
          {demoError ? <p className="mb-3 text-xs text-destructive">{demoError}</p> : null}
          <p className="text-[10px] text-muted-foreground">
            <Trans>
              Demo users can browse your dashboard (Today, Training, Goal, History) but cannot change settings, sync
              data, or modify plans. Share the email and password with anyone you want to demo to.
            </Trans>
          </p>
        </CardContent>
      </Card>

      <Dialog open={!!roleChangeUser} onOpenChange={(open) => { if (!open) setRoleChangeUser(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {roleChangeUser?.is_superuser ? <Trans>Demote to User</Trans> : <Trans>Promote to Admin</Trans>}
            </DialogTitle>
            <DialogDescription>
              {roleChangeUser?.is_superuser ? (
                <Trans>
                  <strong>{roleChangeUser?.email}</strong> will lose admin privileges. They will no longer be able to
                  manage users or invitation codes.
                </Trans>
              ) : (
                <Trans>
                  <strong>{roleChangeUser?.email}</strong> will gain admin privileges. They will be able to manage all
                  users, delete accounts, and generate invitation codes.
                </Trans>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setRoleChangeUser(null)} disabled={changingRole}>
              <Trans>Cancel</Trans>
            </Button>
            <Button type="button" onClick={() => void handleConfirmRoleChange()} disabled={changingRole}>
              {changingRole ? (
                <Trans>Updating…</Trans>
              ) : roleChangeUser?.is_superuser ? (
                <Trans>Demote</Trans>
              ) : (
                <Trans>Promote</Trans>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteUser} onOpenChange={(open) => { if (!open) setDeleteUser(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              <Trans>Delete user</Trans>
            </DialogTitle>
            <DialogDescription>
              <Trans>
                This will permanently delete <strong>{deleteUser?.email}</strong> and all their data (activities,
                config, connections, plans). This cannot be undone.
              </Trans>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDeleteUser(null)} disabled={deleting}>
              <Trans>Cancel</Trans>
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleDeleteUser()} disabled={deleting}>
              {deleting ? <Trans>Deleting…</Trans> : <Trans>Delete user</Trans>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
