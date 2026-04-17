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
import { Users, Ticket, Copy, Check, Trash2, Plus, ShieldCheck, ChevronUp, ChevronDown } from 'lucide-react';

interface UserInfo {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
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

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/api/admin/users`, { headers: getAuthHeaders() }).then((r) => r.json()),
      fetch(`${API_BASE}/api/admin/invitations`, { headers: getAuthHeaders() }).then((r) => r.json()),
    ])
      .then(([u, i]) => {
        setUsers(u.users || []);
        setInvitations(i.invitations || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, []);

  // Redirect non-admins (after all hooks to satisfy Rules of Hooks)
  if (!isAdmin) return <Navigate to="/" replace />;

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
        <h1 className="text-2xl font-bold text-foreground">Admin</h1>
        <p className="text-sm text-muted-foreground mt-1">Manage users and invitation codes</p>
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
                Users <Badge variant="secondary" className="ml-2">{users.length}</Badge>
              </CardTitle>
              <CardDescription className="text-xs">Registered accounts</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Registered</TableHead>
                <TableHead className="w-32 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">
                    {u.email}
                    {u.email === currentEmail && (
                      <span className="text-xs text-muted-foreground ml-2">(you)</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.is_superuser ? (
                      <Badge className="text-xs"><ShieldCheck className="h-3 w-3 mr-1" />Admin</Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs">User</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground font-data">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                  </TableCell>
                  <TableCell className="text-right">
                    {u.email !== currentEmail && (
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-muted-foreground hover:text-foreground"
                          onClick={() => setRoleChangeUser(u)}
                          title={u.is_superuser ? 'Demote to User' : 'Promote to Admin'}
                        >
                          {u.is_superuser ? (
                            <><ChevronDown className="h-3 w-3 mr-1" />Demote</>
                          ) : (
                            <><ChevronUp className="h-3 w-3 mr-1" />Promote</>
                          )}
                        </Button>
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
                  Invitation Codes <Badge variant="secondary" className="ml-2">{invitations.length}</Badge>
                </CardTitle>
                <CardDescription className="text-xs">One-time codes for new user registration</CardDescription>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Input
                placeholder="Note (optional)"
                value={inviteNote}
                onChange={(e) => setInviteNote(e.target.value)}
                className="h-8 w-40 text-xs"
                onKeyDown={(e) => { if (e.key === 'Enter') handleGenerateInvite(); }}
              />
              <Button size="sm" onClick={handleGenerateInvite}>
                <Plus className="h-3 w-3 mr-1" />
                Generate
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Newly generated code callout */}
          {newCode && (
            <div className="flex items-center justify-between rounded-lg bg-primary/10 border border-primary/30 px-4 py-3 mb-4">
              <div>
                <p className="text-xs text-muted-foreground">New invitation code:</p>
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
                <TableHead>Code</TableHead>
                <TableHead>Note</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Used By</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-6">
                    No invitation codes yet. Generate one to invite a user.
                  </TableCell>
                </TableRow>
              ) : (
                invitations.map((inv) => (
                  <TableRow key={inv.id} className={!inv.is_active || inv.used_by ? 'opacity-50' : ''}>
                    <TableCell>
                      <button
                        className="font-data text-sm tracking-wider hover:text-primary transition-colors"
                        onClick={() => copyCode(inv.code)}
                        title="Click to copy"
                      >
                        {inv.code}
                      </button>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{inv.note || '—'}</TableCell>
                    <TableCell>
                      {inv.used_by ? (
                        <Badge variant="secondary" className="text-[10px]">Used</Badge>
                      ) : inv.is_active ? (
                        <Badge className="text-[10px] bg-primary/20 text-primary border-primary/30">Available</Badge>
                      ) : (
                        <Badge variant="outline" className="text-[10px] text-destructive">Revoked</Badge>
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
                          Revoke
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

      {/* Role Change Confirmation */}
      <Dialog open={!!roleChangeUser} onOpenChange={(open) => { if (!open) setRoleChangeUser(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {roleChangeUser?.is_superuser ? 'Demote to User' : 'Promote to Admin'}
            </DialogTitle>
            <DialogDescription>
              {roleChangeUser?.is_superuser ? (
                <>
                  <strong>{roleChangeUser?.email}</strong> will lose admin privileges.
                  They will no longer be able to manage users or invitation codes.
                </>
              ) : (
                <>
                  <strong>{roleChangeUser?.email}</strong> will gain admin privileges.
                  They will be able to manage all users, delete accounts, and generate invitation codes.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRoleChangeUser(null)} disabled={changingRole}>
              Cancel
            </Button>
            <Button onClick={handleConfirmRoleChange} disabled={changingRole}>
              {changingRole ? 'Updating...' : roleChangeUser?.is_superuser ? 'Demote' : 'Promote'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete User Confirmation */}
      <Dialog open={!!deleteUser} onOpenChange={(open) => { if (!open) setDeleteUser(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete User</DialogTitle>
            <DialogDescription>
              This will permanently delete <strong>{deleteUser?.email}</strong> and all their data
              (activities, config, connections, plans). This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteUser(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteUser} disabled={deleting}>
              {deleting ? 'Deleting...' : 'Delete User'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
