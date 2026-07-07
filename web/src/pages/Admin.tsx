import { useState, useEffect } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { API_BASE, getAuthHeaders } from '@/hooks/useApi';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Users, Ticket, Copy, Check, Trash2, Plus, ShieldCheck, ChevronUp, ChevronDown, Eye, Megaphone, MessageSquarePlus, ExternalLink, RotateCcw, RefreshCw, UserPlus, Activity, Send, AlertTriangle, Mail } from 'lucide-react';
import type { SystemAnnouncement, AdminFeedbackItem, AdminFeedbackSyncResult, FeedbackStatus, AdminConfig, WaitlistSignupItem, WaitlistInviteResult, ServiceIncident, IncidentImpact, IncidentStatus } from '@/types/api';
import AdminFeedbackImages from '@/components/AdminFeedbackImages';
import { Trans, useLingui } from '@lingui/react/macro';

// Surface the rows an admin should act on (needs_review, failed) at the top.
const FEEDBACK_STATUS_ORDER: Record<string, number> = {
  needs_review: 0,
  failed: 1,
  new: 2,
  triaged: 3,
  issue_created: 4,
  resolved: 5,
  rejected: 6,
};

// Within a status, show the most urgent tickets first.
const FEEDBACK_PRIORITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

// Outline-badge tint per priority (amber/destructive already used elsewhere on
// this page; primary/green stays reserved for positive signals like resolved).
const FEEDBACK_PRIORITY_CLASS: Record<string, string> = {
  critical: 'text-destructive border-destructive/40',
  high: 'text-amber-600 border-amber-500/40',
  medium: 'text-muted-foreground',
  low: 'text-muted-foreground',
};

function feedbackStatusVariant(status: string): 'default' | 'destructive' | 'outline' | 'secondary' {
  if (status === 'issue_created') return 'default';
  if (status === 'failed') return 'destructive';
  if (status === 'resolved') return 'outline';
  return 'secondary';
}

interface UserInfo {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_demo: boolean;
  demo_of: string | null;
  demo_of_email: string | null;
  created_at: string | null;
}

interface InvitationInfo {
  id: number;
  code: string;
  note: string;
  is_active: boolean;
  created_at: string | null;
  used_by: string | null;
  used_at: string | null;
}

export default function Admin() {
  const { isAdmin, email: currentEmail } = useAuth();
  const { t } = useLingui();
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [invitations, setInvitations] = useState<InvitationInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteNote, setInviteNote] = useState('');
  const [newCode, setNewCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [deleteUser, setDeleteUser] = useState<UserInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [roleChangeUser, setRoleChangeUser] = useState<UserInfo | null>(null);
  const [changingRole, setChangingRole] = useState(false);
  const [demoEmail, setDemoEmail] = useState('');
  const [demoPassword, setDemoPassword] = useState('');
  const [creatingDemo, setCreatingDemo] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);

  // Announcements
  const [announcements, setAnnouncements] = useState<SystemAnnouncement[]>([]);
  const [newTitle, setNewTitle] = useState('');
  const [newBody, setNewBody] = useState('');
  const [newType, setNewType] = useState<'info' | 'warning' | 'success'>('info');
  const [newLinkText, setNewLinkText] = useState('');
  const [newLinkUrl, setNewLinkUrl] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Service incidents (public status page)
  const [incidents, setIncidents] = useState<ServiceIncident[]>([]);
  const [incTitle, setIncTitle] = useState('');
  const [incImpact, setIncImpact] = useState<IncidentImpact>('minor');
  const [incBody, setIncBody] = useState('');
  const [incCreating, setIncCreating] = useState(false);
  const [incError, setIncError] = useState<string | null>(null);
  const [incUpdateBody, setIncUpdateBody] = useState<Record<number, string>>({});

  // Feedback
  const [feedback, setFeedback] = useState<AdminFeedbackItem[]>([]);
  const [feedbackBusy, setFeedbackBusy] = useState<number | null>(null);
  const [feedbackFilter, setFeedbackFilter] = useState<'active' | 'all' | FeedbackStatus>('active');
  const [feedbackSyncing, setFeedbackSyncing] = useState(false);
  const [feedbackSyncMsg, setFeedbackSyncMsg] = useState<string | null>(null);

  // Registration gate + waitlist
  const [config, setConfig] = useState<AdminConfig | null>(null);
  const [maxUsersInput, setMaxUsersInput] = useState('');
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMsg, setConfigMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [waitlist, setWaitlist] = useState<WaitlistSignupItem[]>([]);
  const [invitingId, setInvitingId] = useState<number | null>(null);
  const [inviteResults, setInviteResults] = useState<Record<number, WaitlistInviteResult>>({});
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const feedbackQuery = (filter: string) => (filter === 'all' ? '' : `?status=${filter}`);

  // Refetch only the feedback list under a given status filter. Cheaper than a
  // full fetchData() when just the ticket table needs to change.
  const loadFeedback = (filter: 'active' | 'all' | FeedbackStatus) =>
    fetch(`${API_BASE}/api/admin/feedback${feedbackQuery(filter)}`, { headers: getAuthHeaders() })
      .then((r) => (r.ok ? r.json() : []))
      .then((f) => setFeedback(Array.isArray(f) ? f : []))
      .catch(() => {});

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/api/admin/users`, { headers: getAuthHeaders() }).then((r) => r.json()),
      fetch(`${API_BASE}/api/admin/invitations`, { headers: getAuthHeaders() }).then((r) => r.json()),
      fetch(`${API_BASE}/api/announcements`, { headers: getAuthHeaders() }).then((r) => r.ok ? r.json() : []),
      fetch(`${API_BASE}/api/admin/feedback${feedbackQuery(feedbackFilter)}`, { headers: getAuthHeaders() }).then((r) => r.ok ? r.json() : []),
      fetch(`${API_BASE}/api/admin/config`, { headers: getAuthHeaders() }).then((r) => r.ok ? r.json() : null),
      fetch(`${API_BASE}/api/admin/waitlist`, { headers: getAuthHeaders() }).then((r) => r.ok ? r.json() : { signups: [] }),
      fetch(`${API_BASE}/api/admin/incidents`, { headers: getAuthHeaders() }).then((r) => r.ok ? r.json() : []),
    ])
      .then(([u, i, a, f, cfg, wl, inc]) => {
        setUsers(u.users || []);
        setInvitations(i.invitations || []);
        setAnnouncements(Array.isArray(a) ? a : []);
        setFeedback(Array.isArray(f) ? f : []);
        if (cfg) { setConfig(cfg); setMaxUsersInput(String(cfg.registration.max_users)); }
        setWaitlist(wl?.signups || []);
        setIncidents(Array.isArray(inc) ? inc : []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  const handleCreateAnnouncement = async () => {
    if (!newTitle.trim()) return;
    setCreating(true);
    setCreateError(null);
    const res = await fetch(`${API_BASE}/api/admin/announcements`, {
      method: 'POST',
      headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: newTitle.trim(),
        body: newBody.trim(),
        type: newType,
        link_text: newLinkText.trim() || null,
        link_url: newLinkUrl.trim() || null,
      }),
    });
    setCreating(false);
    if (res.ok) {
      const created = await res.json();
      setAnnouncements((prev) => [created, ...prev]);
      setNewTitle(''); setNewBody(''); setNewType('info'); setNewLinkText(''); setNewLinkUrl('');
    } else {
      setCreateError('Failed to create announcement');
    }
  };

  const handleToggleAnnouncement = async (ann: SystemAnnouncement) => {
    const res = await fetch(`${API_BASE}/api/admin/announcements/${ann.id}`, {
      method: 'PATCH',
      headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !ann.is_active }),
    });
    if (res.ok) {
      const updated = await res.json();
      setAnnouncements((prev) => prev.map((a) => a.id === ann.id ? updated : a));
    }
  };

  const handleDeleteAnnouncement = async (id: number) => {
    const res = await fetch(`${API_BASE}/api/admin/announcements/${id}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (res.ok) setAnnouncements((prev) => prev.filter((a) => a.id !== id));
  };

  const handleCreateIncident = async () => {
    if (!incTitle.trim()) return;
    setIncCreating(true);
    setIncError(null);
    const res = await fetch(`${API_BASE}/api/admin/incidents`, {
      method: 'POST',
      headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: incTitle.trim(), impact: incImpact, body: incBody.trim() }),
    });
    setIncCreating(false);
    if (res.ok) {
      const created = await res.json();
      setIncidents((prev) => [created, ...prev]);
      setIncTitle(''); setIncBody(''); setIncImpact('minor');
    } else {
      setIncError('Failed to create incident');
    }
  };

  const handleIncidentUpdate = async (inc: ServiceIncident, status: IncidentStatus) => {
    const body = (incUpdateBody[inc.id] || '').trim();
    const res = await fetch(`${API_BASE}/api/admin/incidents/${inc.id}/updates`, {
      method: 'POST',
      headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, body }),
    });
    if (res.ok) {
      const updated = await res.json();
      setIncidents((prev) => prev.map((x) => (x.id === inc.id ? updated : x)));
      setIncUpdateBody((prev) => ({ ...prev, [inc.id]: '' }));
    }
  };

  const handleDeleteIncident = async (id: number) => {
    const res = await fetch(`${API_BASE}/api/admin/incidents/${id}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (res.ok) setIncidents((prev) => prev.filter((x) => x.id !== id));
  };

  const handleFeedbackAction = async (id: number, action: 'retry' | 'reject' | 'approve') => {
    setFeedbackBusy(id);
    const res = await fetch(`${API_BASE}/api/admin/feedback/${id}`, {
      method: 'PATCH',
      headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    setFeedbackBusy(null);
    if (res.ok) {
      // Refetch under the current filter so a row that moved to a now-hidden
      // status (e.g. reject → rejected) drops out of the view immediately.
      await loadFeedback(feedbackFilter);
    } else {
      // Approve/retry can fail server-side (e.g. GitHub publish error marks the
      // row failed). Resync so the table reflects the persisted state.
      fetchData();
    }
  };

  const handleFeedbackFilterChange = (value: string | null) => {
    if (!value) return;
    const filter = value as 'active' | 'all' | FeedbackStatus;
    setFeedbackFilter(filter);
    loadFeedback(filter);
  };

  const handleFeedbackSync = async () => {
    setFeedbackSyncing(true);
    setFeedbackSyncMsg(null);
    const res = await fetch(`${API_BASE}/api/admin/feedback/sync`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
    setFeedbackSyncing(false);
    if (res.ok) {
      const r: AdminFeedbackSyncResult = await res.json();
      setFeedbackSyncMsg(
        !r.configured
          ? t`GitHub isn't configured — nothing to sync.`
          : r.updated > 0
            ? t`Updated ${r.updated} of ${r.checked} linked ticket(s).`
            : t`All ${r.checked} linked ticket(s) already up to date.`,
      );
      await loadFeedback(feedbackFilter);
    } else {
      setFeedbackSyncMsg(t`Sync failed.`);
    }
  };

  const patchConfig = async (payload: { registration_open?: boolean; registration_max_users?: number }) => {
    if (!config) return;
    setSavingConfig(true);
    setConfigMsg(null);
    // Optimistically reflect the operator's intent so the toggle feels instant;
    // the authoritative server snapshot below reconciles it (and the error path
    // re-fetches), so a slow or unparseable response can't leave the UI stale.
    const prev = config;
    if (payload.registration_open !== undefined) {
      setConfig({
        ...config,
        registration: {
          ...config.registration,
          flag_enabled: payload.registration_open,
          registration_open: payload.registration_open && !config.registration.cap_reached,
        },
      });
    }
    try {
      const res = await fetch(`${API_BASE}/api/admin/config`, {
        method: 'PATCH',
        headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(String(res.status));
      const cfg: AdminConfig = await res.json();
      setConfig(cfg);
      setMaxUsersInput(String(cfg.registration.max_users));
      setConfigMsg({ ok: true, text: t`Saved` });
    } catch {
      // Reconcile against the server; fall back to reverting the optimistic flip.
      try {
        const g = await fetch(`${API_BASE}/api/admin/config`, { headers: getAuthHeaders() });
        if (g.ok) {
          const cfg: AdminConfig = await g.json();
          setConfig(cfg);
          setMaxUsersInput(String(cfg.registration.max_users));
        } else {
          setConfig(prev);
        }
      } catch {
        setConfig(prev);
      }
      setConfigMsg({ ok: false, text: t`Couldn't save. Check your connection and try again.` });
    } finally {
      setSavingConfig(false);
    }
  };

  const handleToggleRegistration = () => {
    if (!config) return;
    patchConfig({ registration_open: !config.registration.flag_enabled });
  };

  const handleSaveMaxUsers = () => {
    const n = parseInt(maxUsersInput, 10);
    if (!Number.isFinite(n) || n < 0) return;
    patchConfig({ registration_max_users: n });
  };

  const handleInviteWaitlist = async (row: WaitlistSignupItem) => {
    setInvitingId(row.id);
    const res = await fetch(`${API_BASE}/api/admin/waitlist/${row.id}/invite`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
    setInvitingId(null);
    if (res.ok) {
      const result: WaitlistInviteResult = await res.json();
      setInviteResults((prev) => ({ ...prev, [row.id]: result }));
      fetchData();
    }
  };

  const copyInviteCode = (code: string) => {
    navigator.clipboard?.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 1500);
  };

  useEffect(() => { fetchData(); }, []);

  // Redirect non-admins (after all hooks to satisfy Rules of Hooks)
  if (!isAdmin) return <Navigate to="/today" replace />;

  const handleGenerateInvite = async () => {
    const res = await fetch(`${API_BASE}/api/admin/invitations`, {
      method: 'POST',
      headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: inviteNote }),
    });
    const data = await res.json();
    setNewCode(data.code);
    setInviteNote('');
    fetchData();
  };

  const handleRevokeInvite = async (id: number) => {
    await fetch(`${API_BASE}/api/admin/invitations/${id}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    fetchData();
  };

  const handleDeleteUser = async () => {
    if (!deleteUser) return;
    setDeleting(true);
    await fetch(`${API_BASE}/api/admin/users/${deleteUser.id}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    setDeleteUser(null);
    setDeleting(false);
    fetchData();
  };

  const handleConfirmRoleChange = async () => {
    if (!roleChangeUser) return;
    setChangingRole(true);
    await fetch(`${API_BASE}/api/admin/users/${roleChangeUser.id}/role`, {
      method: 'PATCH',
      headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_superuser: !roleChangeUser.is_superuser }),
    });
    setRoleChangeUser(null);
    setChangingRole(false);
    fetchData();
  };

  const handleCreateDemo = async () => {
    if (!demoEmail.trim() || !demoPassword.trim()) return;
    setCreatingDemo(true);
    setDemoError(null);
    try {
      const res = await fetch(`${API_BASE}/api/admin/demo-accounts`, {
        method: 'POST',
        headers: { ...getAuthHeaders() as Record<string, string>, 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: demoEmail, password: demoPassword }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setDemoError(data?.detail || t`Failed (HTTP ${res.status})`);
      } else {
        setDemoEmail('');
        setDemoPassword('');
        fetchData();
      }
    } catch {
      setDemoError(t`Network error. Is the server running?`);
    }
    setCreatingDemo(false);
  };

  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-48 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground"><Trans>Admin</Trans></h1>
        <p className="text-sm text-muted-foreground mt-1"><Trans>Manage users and invitation codes</Trans></p>
      </div>

      {/* Registration gate + seat cap */}
      {config && (
        <Card className="mb-8">
          <CardHeader>
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <UserPlus className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground">
                  <Trans>Registration</Trans>
                  {config.registration.registration_open
                    ? <Badge className="ml-2 bg-primary/15 text-primary border-primary/30"><Trans>Open</Trans></Badge>
                    : <Badge variant="secondary" className="ml-2">{config.registration.cap_reached ? <Trans>Closed · cap reached</Trans> : <Trans>Closed</Trans>}</Badge>}
                </CardTitle>
                <CardDescription className="text-xs"><Trans>Control self-registration and the committed-seat cap</Trans></CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {!config.email_configured && (
              <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <span><Trans>Email is not configured. Open sign-ups will NOT be email-verified, and invitation codes can't be emailed automatically — you'll copy them by hand. Set the SMTP env vars to enable both.</Trans></span>
              </div>
            )}

            <div className="flex flex-wrap items-end gap-6">
              <div>
                <p className="text-xs text-muted-foreground mb-1"><Trans>Self-registration</Trans></p>
                <Button
                  variant={config.registration.flag_enabled ? 'default' : 'outline'}
                  size="sm"
                  onClick={handleToggleRegistration}
                  disabled={savingConfig}
                >
                  {config.registration.flag_enabled ? <Trans>Enabled — click to close</Trans> : <Trans>Disabled — click to open</Trans>}
                </Button>
                {configMsg && (
                  <p className={`mt-1.5 text-xs ${configMsg.ok ? 'text-primary' : 'text-destructive'}`}>{configMsg.text}</p>
                )}
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block"><Trans>Seat cap</Trans></label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    value={maxUsersInput}
                    onChange={(e) => setMaxUsersInput(e.target.value)}
                    className="h-8 w-24 text-xs font-data"
                  />
                  <Button size="sm" variant="outline" onClick={handleSaveMaxUsers} disabled={savingConfig}><Trans>Save</Trans></Button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              <div className="rounded-lg border border-border px-3 py-2">
                <p className="text-[11px] text-muted-foreground"><Trans>Registered</Trans></p>
                <p className="text-lg font-semibold font-data text-foreground">{config.registration.registered_users}</p>
              </div>
              <div className="rounded-lg border border-border px-3 py-2">
                <p className="text-[11px] text-muted-foreground"><Trans>Outstanding codes</Trans></p>
                <p className="text-lg font-semibold font-data text-foreground">{config.registration.outstanding_invitations}</p>
              </div>
              <div className={`rounded-lg border px-3 py-2 ${config.registration.cap_reached ? 'border-amber-500/40 bg-amber-500/5' : 'border-border'}`}>
                <p className="text-[11px] text-muted-foreground"><Trans>Committed / cap</Trans></p>
                <p className="text-lg font-semibold font-data text-foreground">{config.registration.committed_seats} / {config.registration.max_users}</p>
              </div>
              <div className="rounded-lg border border-border px-3 py-2">
                <p className="text-[11px] text-muted-foreground"><Trans>Remaining</Trans></p>
                <p className="text-lg font-semibold font-data text-foreground">{config.registration.remaining}</p>
              </div>
              <div className="rounded-lg border border-border px-3 py-2">
                <p className="text-[11px] text-muted-foreground inline-flex items-center gap-1"><Activity className="h-3 w-3" /><Trans>DAU</Trans></p>
                <p className="text-lg font-semibold font-data text-foreground">{config.activity.dau}</p>
              </div>
              <div className="rounded-lg border border-border px-3 py-2">
                <p className="text-[11px] text-muted-foreground inline-flex items-center gap-1"><Activity className="h-3 w-3" /><Trans>WAU</Trans></p>
                <p className="text-lg font-semibold font-data text-foreground">{config.activity.wau}</p>
              </div>
            </div>
            <p className="text-[11px] text-muted-foreground">
              <Trans>Sending an invitation reserves a seat. Self-registration auto-closes at the cap; review readiness before raising it.</Trans>
            </p>
          </CardContent>
        </Card>
      )}

      {/* Users */}
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Users className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">
                <Trans>Users</Trans> <Badge variant="secondary" className="ml-2">{users.length}</Badge>
              </CardTitle>
              <CardDescription className="text-xs"><Trans>Registered accounts</Trans></CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
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
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">
                    {u.email}
                    {u.email === currentEmail && (
                      <span className="text-xs text-muted-foreground ml-2">(<Trans>you</Trans>)</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.is_demo ? (
                      <div>
                        <Badge variant="outline" className="text-xs text-amber-600 border-amber-500/40"><Trans>Demo</Trans></Badge>
                        {u.demo_of_email && (
                          <span className="text-[10px] text-muted-foreground ml-1.5"><Trans>mirrors {u.demo_of_email}</Trans></span>
                        )}
                      </div>
                    ) : u.is_superuser ? (
                      <Badge className="text-xs"><ShieldCheck className="h-3 w-3 mr-1" /><Trans>Admin</Trans></Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs"><Trans>User</Trans></Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground font-data">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                  </TableCell>
                  <TableCell className="text-right">
                    {u.email !== currentEmail && (
                      <div className="flex items-center justify-end gap-1">
                        {!u.is_demo && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs text-muted-foreground hover:text-foreground"
                            onClick={() => setRoleChangeUser(u)}
                            title={u.is_superuser ? t`Demote to User` : t`Promote to Admin`}
                          >
                            {u.is_superuser ? (
                              <><ChevronDown className="h-3 w-3 mr-1" /><Trans>Demote</Trans></>
                            ) : (
                              <><ChevronUp className="h-3 w-3 mr-1" /><Trans>Promote</Trans></>
                            )}
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-muted-foreground hover:text-destructive"
                          onClick={() => setDeleteUser(u)}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Invitations */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Ticket className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground">
                  <Trans>Invitation Codes</Trans> <Badge variant="secondary" className="ml-2">{invitations.length}</Badge>
                </CardTitle>
                <CardDescription className="text-xs"><Trans>One-time codes for new user registration</Trans></CardDescription>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Input
                placeholder={t`Note (optional)`}
                value={inviteNote}
                onChange={(e) => setInviteNote(e.target.value)}
                className="h-8 w-40 text-xs"
                onKeyDown={(e) => { if (e.key === 'Enter') handleGenerateInvite(); }}
              />
              <Button size="sm" onClick={handleGenerateInvite}>
                <Plus className="h-3 w-3 mr-1" />
                <Trans>Generate</Trans>
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Newly generated code callout */}
          {newCode && (
            <div className="flex items-center justify-between rounded-lg bg-primary/10 border border-primary/30 px-4 py-3 mb-4">
              <div>
                <p className="text-xs text-muted-foreground"><Trans>New invitation code:</Trans></p>
                <p className="text-lg font-bold font-data text-primary tracking-wider">{newCode}</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => copyCode(newCode)}>
                {copied ? <Check className="h-4 w-4 text-primary" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          )}

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead><Trans>Code</Trans></TableHead>
                <TableHead><Trans>Note</Trans></TableHead>
                <TableHead><Trans>Status</Trans></TableHead>
                <TableHead><Trans>Used By</Trans></TableHead>
                <TableHead><Trans>Created</Trans></TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-6">
                    <Trans>No invitation codes yet. Generate one to invite a user.</Trans>
                  </TableCell>
                </TableRow>
              ) : (
                invitations.map((inv) => (
                  <TableRow key={inv.id} className={!inv.is_active || inv.used_by ? 'opacity-50' : ''}>
                    <TableCell>
                      <button
                        className="font-data text-sm tracking-wider hover:text-primary transition-colors"
                        onClick={() => copyCode(inv.code)}
                        title={t`Click to copy`}
                      >
                        {inv.code}
                      </button>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{inv.note || '—'}</TableCell>
                    <TableCell>
                      {inv.used_by ? (
                        <Badge variant="secondary" className="text-[10px]"><Trans>Used</Trans></Badge>
                      ) : inv.is_active ? (
                        <Badge className="text-[10px] bg-primary/20 text-primary border-primary/30"><Trans>Available</Trans></Badge>
                      ) : (
                        <Badge variant="outline" className="text-[10px] text-destructive"><Trans>Revoked</Trans></Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{inv.used_by || '—'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground font-data">
                      {inv.created_at ? new Date(inv.created_at).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell>
                      {inv.is_active && !inv.used_by && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-muted-foreground hover:text-destructive"
                          onClick={() => handleRevokeInvite(inv.id)}
                        >
                          <Trans>Revoke</Trans>
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Waitlist */}
      <Card className="mt-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Mail className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground">
                <Trans>Waitlist</Trans> <Badge variant="secondary" className="ml-2">{waitlist.length}</Badge>
              </CardTitle>
              <CardDescription className="text-xs"><Trans>Prospective users — generate an invitation code and email it</Trans></CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {Object.keys(inviteResults).length > 0 && (
            <div className="mb-4 space-y-2">
              {Object.entries(inviteResults).map(([id, r]) => (
                <div key={id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-xs">
                  <span className="text-muted-foreground">
                    {r.sent
                      ? <Trans>Invitation emailed to {r.email} · code {r.code}</Trans>
                      : <Trans>Code {r.code} created for {r.email}. Email not sent — copy it or use the link.</Trans>}
                  </span>
                  <div className="flex items-center gap-3">
                    <button type="button" className="inline-flex items-center gap-1 font-data text-muted-foreground hover:text-foreground" onClick={() => copyInviteCode(r.code)}>
                      {copiedCode === r.code ? <Check className="h-3 w-3 text-primary" /> : <Copy className="h-3 w-3" />}
                      <Trans>Copy code</Trans>
                    </button>
                    {!r.sent && (
                      <a className="inline-flex items-center gap-1 text-primary hover:underline" href={`mailto:${r.email}?subject=${encodeURIComponent('Your Praxys invitation')}&body=${encodeURIComponent(`Your Praxys invitation code: ${r.code}\n\nFinish registering here: ${r.invite_url}`)}`}>
                        <Mail className="h-3 w-3" /><Trans>Email link</Trans>
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
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
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground py-6">
                    <Trans>No waitlist signups yet.</Trans>
                  </TableCell>
                </TableRow>
              ) : (
                waitlist.map((s) => {
                  const codeButton = s.invitation_code ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 text-xs font-data text-muted-foreground hover:text-foreground"
                      onClick={() => copyInviteCode(s.invitation_code!)}
                      title={t`Copy code`}
                    >
                      {s.invitation_code}
                      {copiedCode === s.invitation_code ? <Check className="h-3 w-3 text-primary" /> : <Copy className="h-3 w-3" />}
                    </button>
                  ) : null;
                  return (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">{s.email}</TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[16rem] truncate">{s.note || '—'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground font-data">{s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}</TableCell>
                    <TableCell>
                      {s.registered ? (
                        <div className="flex items-center gap-1.5">
                          <Badge className="bg-primary text-primary-foreground border-transparent"><Trans>Joined</Trans></Badge>
                          {codeButton}
                        </div>
                      ) : s.invited_at ? (
                        <div className="flex items-center gap-1.5">
                          <Badge className="bg-primary/15 text-primary border-primary/30"><Trans>Invited</Trans></Badge>
                          {codeButton}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {s.registered ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : (
                        <Button
                          size="sm"
                          variant={s.invited_at ? 'outline' : 'default'}
                          onClick={() => handleInviteWaitlist(s)}
                          disabled={invitingId === s.id}
                        >
                          <Send className="h-3 w-3 mr-1" />
                          {invitingId === s.id ? <Trans>Sending…</Trans> : s.invited_at ? <Trans>Re-invite</Trans> : <Trans>Invite</Trans>}
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

      {/* Demo Accounts */}
      <Card className="mt-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600">
              <Eye className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-semibold text-foreground"><Trans>Demo Accounts</Trans></CardTitle>
              <CardDescription className="text-xs">
                <Trans>Read-only accounts that mirror your dashboard data</Trans>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-2 mb-4">
            <div className="space-y-1 flex-1">
              <label className="text-xs text-muted-foreground"><Trans>Email</Trans></label>
              <Input
                type="email"
                placeholder={t`demo@example.com`}
                value={demoEmail}
                onChange={(e) => setDemoEmail(e.target.value)}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1 flex-1">
              <label className="text-xs text-muted-foreground"><Trans>Password</Trans></label>
              <Input
                type="password"
                placeholder={t`demo-password`}
                value={demoPassword}
                onChange={(e) => setDemoPassword(e.target.value)}
                className="h-8 text-xs font-data"
              />
            </div>
            <Button
              size="sm"
              onClick={handleCreateDemo}
              disabled={creatingDemo || !demoEmail.trim() || !demoPassword.trim()}
            >
              <Plus className="h-3 w-3 mr-1" />
              {creatingDemo ? <Trans>Creating...</Trans> : <Trans>Create</Trans>}
            </Button>
          </div>
          {demoError && (
            <p className="text-xs text-destructive mb-3">{demoError}</p>
          )}
          <p className="text-[10px] text-muted-foreground">
            <Trans>Demo users can browse your dashboard (Today, Training, Goal, History) but cannot change settings, sync data, or modify plans.
            Share the email and password with anyone you want to demo to.</Trans>
          </p>
        </CardContent>
      </Card>

      {/* Role Change Confirmation */}
      <Dialog open={!!roleChangeUser} onOpenChange={(open) => { if (!open) setRoleChangeUser(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {roleChangeUser?.is_superuser ? <Trans>Demote to User</Trans> : <Trans>Promote to Admin</Trans>}
            </DialogTitle>
            <DialogDescription>
              {roleChangeUser?.is_superuser ? (
                <Trans>
                  <strong>{roleChangeUser?.email}</strong> will lose admin privileges.
                  They will no longer be able to manage users or invitation codes.
                </Trans>
              ) : (
                <Trans>
                  <strong>{roleChangeUser?.email}</strong> will gain admin privileges.
                  They will be able to manage all users, delete accounts, and generate invitation codes.
                </Trans>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRoleChangeUser(null)} disabled={changingRole}>
              <Trans>Cancel</Trans>
            </Button>
            <Button onClick={handleConfirmRoleChange} disabled={changingRole}>
              {changingRole ? <Trans>Updating...</Trans> : roleChangeUser?.is_superuser ? <Trans>Demote</Trans> : <Trans>Promote</Trans>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete User Confirmation */}
      <Dialog open={!!deleteUser} onOpenChange={(open) => { if (!open) setDeleteUser(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle><Trans>Delete User</Trans></DialogTitle>
            <DialogDescription>
              <Trans>
                This will permanently delete <strong>{deleteUser?.email}</strong> and all their data
                (activities, config, connections, plans). This cannot be undone.
              </Trans>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteUser(null)} disabled={deleting}>
              <Trans>Cancel</Trans>
            </Button>
            <Button variant="destructive" onClick={handleDeleteUser} disabled={deleting}>
              {deleting ? <Trans>Deleting...</Trans> : <Trans>Delete User</Trans>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* System Announcements */}
      <Card className="mt-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Megaphone className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-base"><Trans>System Announcements</Trans></CardTitle>
              <CardDescription className="text-xs"><Trans>Dismissible banners shown to all users</Trans></CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Create form */}
          <div className="rounded-lg border border-dashed border-border p-4 space-y-3">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide"><Trans>New announcement</Trans></p>
            <Input
              placeholder={t`Title`}
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
            />
            <Input
              placeholder={t`Body (optional)`}
              value={newBody}
              onChange={(e) => setNewBody(e.target.value)}
            />
            <div className="flex gap-2">
              <select
                value={newType}
                onChange={(e) => setNewType(e.target.value as 'info' | 'warning' | 'success')}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="success">success</option>
              </select>
              <Input
                placeholder={t`Link text (optional)`}
                value={newLinkText}
                onChange={(e) => setNewLinkText(e.target.value)}
              />
              <Input
                placeholder={t`Link URL (optional)`}
                value={newLinkUrl}
                onChange={(e) => setNewLinkUrl(e.target.value)}
              />
            </div>
            {createError && <p className="text-xs text-destructive">{createError}</p>}
            <Button size="sm" onClick={handleCreateAnnouncement} disabled={creating || !newTitle.trim()}>
              <Plus className="h-3.5 w-3.5 mr-1.5" />
              {creating ? <Trans>Creating...</Trans> : <Trans>Create</Trans>}
            </Button>
          </div>

          {/* Existing announcements */}
          {announcements.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4"><Trans>No announcements yet</Trans></p>
          ) : (
            <div className="space-y-2">
              {announcements.map((ann) => (
                <div key={ann.id} className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${ann.is_active ? '' : 'opacity-50'}`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-xs shrink-0">{ann.type}</Badge>
                      <span className="font-medium truncate">{ann.title}</span>
                    </div>
                    {ann.body && <p className="text-xs text-muted-foreground mt-0.5 truncate">{ann.body}</p>}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost" size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => handleToggleAnnouncement(ann)}
                    >
                      {ann.is_active ? <Trans>Deactivate</Trans> : <Trans>Activate</Trans>}
                    </Button>
                    <Button
                      variant="ghost" size="sm"
                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                      onClick={() => handleDeleteAnnouncement(ann.id)}
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

      {/* Service Incidents */}
      <Card className="mt-8">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <div className="flex-1">
              <CardTitle className="text-base"><Trans>Service Incidents</Trans></CardTitle>
              <CardDescription className="text-xs">
                <Trans>Declare incidents shown on the public</Trans>{' '}
                <a href="/status" target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  <Trans>status page</Trans>
                </a>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Create form */}
          <div className="rounded-lg border border-dashed border-border p-4 space-y-3">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide"><Trans>New incident</Trans></p>
            <Input
              placeholder={t`Title (e.g. Elevated API latency)`}
              value={incTitle}
              onChange={(e) => setIncTitle(e.target.value)}
            />
            <Input
              placeholder={t`Opening update message (optional)`}
              value={incBody}
              onChange={(e) => setIncBody(e.target.value)}
            />
            <div className="flex items-center gap-2">
              <select
                value={incImpact}
                onChange={(e) => setIncImpact(e.target.value as IncidentImpact)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="minor">minor</option>
                <option value="major">major</option>
                <option value="critical">critical</option>
              </select>
              <Button size="sm" onClick={handleCreateIncident} disabled={incCreating || !incTitle.trim()}>
                <Plus className="h-3.5 w-3.5 mr-1.5" />
                {incCreating ? <Trans>Creating...</Trans> : <Trans>Open incident</Trans>}
              </Button>
            </div>
            {incError && <p className="text-xs text-destructive">{incError}</p>}
          </div>

          {/* Existing incidents */}
          {incidents.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4"><Trans>No incidents yet</Trans></p>
          ) : (
            <div className="space-y-2">
              {incidents.map((inc) => (
                <div key={inc.id} className={`rounded-lg border p-3 text-sm ${inc.status === 'resolved' ? 'opacity-60' : ''}`}>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs shrink-0">{inc.impact}</Badge>
                    <span className="font-medium truncate flex-1">{inc.title}</span>
                    <Badge variant="secondary" className="text-xs shrink-0">{inc.status}</Badge>
                    <Button
                      variant="ghost" size="sm"
                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                      onClick={() => handleDeleteIncident(inc.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  {inc.status !== 'resolved' && (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Input
                        placeholder={t`Update message (optional)`}
                        value={incUpdateBody[inc.id] || ''}
                        onChange={(e) => setIncUpdateBody((prev) => ({ ...prev, [inc.id]: e.target.value }))}
                        className="h-8 flex-1 min-w-[12rem]"
                      />
                      <Button size="sm" variant="outline" className="h-8" onClick={() => handleIncidentUpdate(inc, 'identified')}>
                        <Trans>Identified</Trans>
                      </Button>
                      <Button size="sm" variant="outline" className="h-8" onClick={() => handleIncidentUpdate(inc, 'monitoring')}>
                        <Trans>Monitoring</Trans>
                      </Button>
                      <Button size="sm" className="h-8" onClick={() => handleIncidentUpdate(inc, 'resolved')}>
                        <Trans>Resolve</Trans>
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* User Feedback */}
      <Card className="mt-8">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <MessageSquarePlus className="h-4 w-4" />
              <div>
                <CardTitle className="text-base flex items-center gap-2">
                  <Trans>User Feedback</Trans>
                  {feedback.some((f) => f.status === 'needs_review') && (
                    <Badge variant="secondary">
                      {feedback.filter((f) => f.status === 'needs_review').length}
                    </Badge>
                  )}
                </CardTitle>
                <CardDescription>
                  <Trans>Bug reports and feature requests submitted from the app. Auto-triaged to GitHub when configured.</Trans>
                </CardDescription>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={feedbackFilter} onValueChange={handleFeedbackFilterChange}>
                <SelectTrigger size="sm" className="w-[150px]">
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
              <Button
                size="sm"
                variant="outline"
                disabled={feedbackSyncing}
                onClick={handleFeedbackSync}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${feedbackSyncing ? 'animate-spin' : ''}`} />
                <Trans>Sync from GitHub</Trans>
              </Button>
            </div>
          </div>
          {feedbackSyncMsg && (
            <p className="mt-2 text-xs text-muted-foreground">{feedbackSyncMsg}</p>
          )}
        </CardHeader>
        <CardContent>
          {feedback.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {feedbackFilter === 'active' ? (
                <Trans>No active tickets.</Trans>
              ) : (
                <Trans>No tickets to show.</Trans>
              )}
            </p>
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
                {[...feedback]
                  .sort((a, b) => {
                    const byStatus =
                      (FEEDBACK_STATUS_ORDER[a.status] ?? 9) - (FEEDBACK_STATUS_ORDER[b.status] ?? 9);
                    if (byStatus !== 0) return byStatus;
                    return (
                      (FEEDBACK_PRIORITY_ORDER[a.priority ?? ''] ?? 9) -
                      (FEEDBACK_PRIORITY_ORDER[b.priority ?? ''] ?? 9)
                    );
                  })
                  .map((f) => (
                  <TableRow key={f.id}>
                    <TableCell><Badge variant="outline">{f.kind}</Badge></TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <Badge
                          variant={feedbackStatusVariant(f.status)}
                          className={f.status === 'resolved' ? 'text-primary border-primary/40' : undefined}
                        >
                          {f.status}
                        </Badge>
                        {f.priority && (
                          <Badge variant="outline" className={FEEDBACK_PRIORITY_CLASS[f.priority]}>
                            {f.priority}
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-sm">
                      <p className="truncate text-sm" title={f.message}>{f.ai_title || f.message}</p>
                      {f.error && <p className="text-xs text-destructive">{f.error}</p>}
                      {f.image_count > 0 && (
                        <>
                          {f.image_sensitive && (
                            <Badge variant="secondary" className="mt-1">
                              <Trans>Screenshot flagged sensitive</Trans>
                            </Badge>
                          )}
                          {f.image_description && (
                            <p
                              className="mt-1 line-clamp-2 text-xs text-muted-foreground"
                              title={f.image_description}
                            >
                              {f.image_description}
                            </p>
                          )}
                          <AdminFeedbackImages feedbackId={f.id} count={f.image_count} />
                        </>
                      )}
                    </TableCell>
                    <TableCell>
                      {f.github_issue_url ? (
                        <a
                          href={f.github_issue_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                        >
                          #{f.github_issue_number}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        {f.status === 'needs_review' && (
                          <Button
                            size="xs"
                            variant="outline"
                            disabled={feedbackBusy === f.id}
                            onClick={() => handleFeedbackAction(f.id, 'approve')}
                          >
                            <Check className="h-3 w-3" />
                            <Trans>Approve & file</Trans>
                          </Button>
                        )}
                        {f.status !== 'issue_created' && f.status !== 'needs_review' && f.status !== 'resolved' && (
                          <Button
                            size="xs"
                            variant="outline"
                            disabled={feedbackBusy === f.id}
                            onClick={() => handleFeedbackAction(f.id, 'retry')}
                          >
                            <RotateCcw className="h-3 w-3" />
                            <Trans>Retry</Trans>
                          </Button>
                        )}
                        {f.status !== 'rejected' && (
                          <Button
                            size="xs"
                            variant="ghost"
                            disabled={feedbackBusy === f.id}
                            onClick={() => handleFeedbackAction(f.id, 'reject')}
                          >
                            <Trans>Reject</Trans>
                          </Button>
                        )}
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
