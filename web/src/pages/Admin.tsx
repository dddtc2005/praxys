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
import { Users, Ticket, Copy, Check, Trash2, Plus, ShieldCheck, ChevronUp, ChevronDown, Eye, Megaphone } from 'lucide-react';
import type { SystemAnnouncement } from '@/types/api';
import { Trans, useLingui } from '@lingui/react/macro';

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

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/api/admin/users`, { headers: getAuthHeaders() }).then((r) => r.json()),
      fetch(`${API_BASE}/api/admin/invitations`, { headers: getAuthHeaders() }).then((r) => r.json()),
      fetch(`${API_BASE}/api/announcements`, { headers: getAuthHeaders() }).then((r) => r.ok ? r.json() : []),
    ])
      .then(([u, i, a]) => {
        setUsers(u.users || []);
        setInvitations(i.invitations || []);
        setAnnouncements(Array.isArray(a) ? a : []);
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
    </div>
  );
}
