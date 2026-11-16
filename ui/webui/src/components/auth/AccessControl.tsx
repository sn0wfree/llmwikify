import { useCallback, useEffect, useState } from 'react';
import { useAuthStore } from '../../stores/authStore';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { Input } from '../ui/input';

/** P5: access-control page — own permission matrix + admin grants CRUD. */

interface GrantRow {
  principal_type: string;
  principal_id: string;
  wiki_id: string;
  can_read: number;
  can_write: number;
  granted_by?: string | null;
  created_at?: string;
}

interface UserRow {
  id: string;
  email: string;
  username: string | null;
  is_first_admin: boolean;
  disabled: boolean;
}

interface GroupRow {
  id: string;
  name: string;
  member_count: number;
}

interface MePermissions {
  accessible_wikis: string[];
  wgrants: Record<string, string>;
  scope: string;
}

async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(path, { ...init, headers });
}

export function AccessControl() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = Boolean(user?.is_first_admin);

  const [perms, setPerms] = useState<MePermissions | null>(null);
  const [grants, setGrants] = useState<GrantRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [groups, setGroups] = useState<GroupRow[]>([]);
  const [error, setError] = useState('');

  // Grant form state
  const [principalType, setPrincipalType] = useState<'user' | 'group'>('user');
  const [principalId, setPrincipalId] = useState('');
  const [wikiId, setWikiId] = useState('');
  const [write, setWrite] = useState(false);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const meRes = await authFetch('/api/auth/me');
      if (meRes.ok) {
        const me = await meRes.json();
        setPerms(me.permissions ?? null);
      }
      if (isAdmin) {
        const [g, u, gr] = await Promise.all([
          authFetch('/api/auth/grants'),
          authFetch('/api/auth/users'),
          authFetch('/api/auth/groups'),
        ]);
        if (g.ok) setGrants((await g.json()).grants ?? []);
        if (u.ok) setUsers((await u.json()).users ?? []);
        if (gr.ok) setGroups((await gr.json()).groups ?? []);
      }
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load');
    }
  }, [isAdmin]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const submitGrant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!principalId || !wikiId) return;
    setBusy(true);
    try {
      const res = await authFetch('/api/auth/grants', {
        method: 'POST',
        body: JSON.stringify({
          principal_type: principalType,
          principal_id: principalId,
          wiki_id: wikiId,
          read: true,
          write,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body?.detail?.detail || body?.detail?.error || 'Grant failed');
      } else {
        setWikiId('');
        setWrite(false);
        await reload();
      }
    } finally {
      setBusy(false);
    }
  };

  const submitRevoke = async (g: GrantRow) => {
    setBusy(true);
    try {
      const res = await authFetch('/api/auth/grants', {
        method: 'DELETE',
        body: JSON.stringify({
          principal_type: g.principal_type,
          principal_id: g.principal_id,
          wiki_id: g.wiki_id,
        }),
      });
      if (res.ok) await reload();
    } finally {
      setBusy(false);
    }
  };

  const labelFor = (g: GrantRow): string => {
    if (g.principal_type === 'public') return 'everyone (authenticated)';
    if (g.principal_type === 'group') {
      const grp = groups.find((x) => x.id === g.principal_id);
      return grp ? `group:${grp.name}` : `group:${g.principal_id.slice(0, 8)}…`;
    }
    const u = users.find((x) => x.id === g.principal_id);
    return u ? u.email : `user:${g.principal_id.slice(0, 8)}…`;
  };

  return (
    <div className="p-6 max-w-4xl space-y-6">
      <h1 className="text-xl font-semibold">Access control</h1>

      {/* ── Own permission matrix ── */}
      <section className="rounded-lg border border-border p-4 space-y-2">
        <h2 className="font-medium">My permissions</h2>
        {perms ? (
          <>
            <div className="text-sm text-muted-foreground">
              scope: <Badge>{perms.scope}</Badge>
            </div>
            <div className="text-sm">
              Accessible wikis:{' '}
              {perms.accessible_wikis.length === 0 ? (
                <span className="text-muted-foreground">none</span>
              ) : (
                perms.accessible_wikis.map((w) => (
                  <Badge key={w} className="mr-1">{w}</Badge>
                ))
              )}
            </div>
            {Object.keys(perms.wgrants).length > 0 && (
              <div className="text-sm text-muted-foreground">
                Snapshot: {Object.entries(perms.wgrants).map(([w, v]) => `${w}=${v}`).join(', ')}
              </div>
            )}
          </>
        ) : (
          <div className="text-sm text-muted-foreground">Loading…</div>
        )}
      </section>

      {error && (
        <div className="text-sm text-destructive">{error}</div>
      )}

      {/* ── Admin: grants CRUD ── */}
      {isAdmin && (
        <section className="rounded-lg border border-border p-4 space-y-4">
          <h2 className="font-medium">Grants</h2>

          <form onSubmit={submitGrant} className="flex flex-wrap gap-2 items-end">
            <label className="text-sm">
              Subject type
              <select
                className="ml-2 border rounded px-2 py-1 bg-background"
                value={principalType}
                onChange={(e) => setPrincipalType(e.target.value as 'user' | 'group')}
              >
                <option value="user">user</option>
                <option value="group">group</option>
              </select>
            </label>
            <label className="text-sm flex-1 min-w-[180px]">
              Subject
              <select
                className="ml-2 w-full border rounded px-2 py-1 bg-background"
                value={principalId}
                onChange={(e) => setPrincipalId(e.target.value)}
                required
              >
                <option value="">— select —</option>
                {principalType === 'user'
                  ? users
                      .filter((u) => !u.disabled)
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.email}{u.is_first_admin ? ' (admin)' : ''}
                        </option>
                      ))
                  : groups.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name} ({g.member_count})
                      </option>
                    ))}
              </select>
            </label>
            <label className="text-sm">
              Wiki
              <Input
                className="ml-2 w-32"
                value={wikiId}
                onChange={(e) => setWikiId(e.target.value)}
                placeholder="wiki-id or *"
                required
              />
            </label>
            <label className="text-sm flex items-center gap-1">
              <input
                type="checkbox"
                checked={write}
                onChange={(e) => setWrite(e.target.checked)}
              />
              write
            </label>
            <Button type="submit" disabled={busy}>
              Grant
            </Button>
          </form>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground border-b">
                <th className="py-1">Subject</th>
                <th className="py-1">Wiki</th>
                <th className="py-1">Access</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {grants.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-2 text-muted-foreground">
                    No grants yet.
                  </td>
                </tr>
              )}
              {grants.map((g) => (
                <tr key={`${g.principal_type}:${g.principal_id}:${g.wiki_id}`} className="border-b border-border/50">
                  <td className="py-1">{labelFor(g)}</td>
                  <td className="py-1">
                    <Badge>{g.wiki_id}</Badge>
                  </td>
                  <td className="py-1">
                    {g.can_write ? 'read+write' : g.can_read ? 'read' : 'none'}
                  </td>
                  <td className="py-1 text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => void submitRevoke(g)}
                    >
                      Revoke
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
