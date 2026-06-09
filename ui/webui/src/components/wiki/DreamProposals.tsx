import { useState, useEffect, useCallback } from 'react';
import { api, DreamProposal } from '../../api';
import { useToast } from './Toast';
import { useWikiStore } from '../../stores/wikiStore';
import { EmptyState } from '../agent/StateViews';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';

export function DreamProposals() {
  const [groups, setGroups] = useState<Record<string, DreamProposal[]>>({});
  const [stats, setStats] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [showApplyConfirm, setShowApplyConfirm] = useState(false);
  const { addToast } = useToast();
  const { currentWikiId } = useWikiStore();

  const loadProposals = useCallback(async () => {
    try {
      const data = await api.dream.proposals(currentWikiId || undefined);
      setGroups(data.proposals);
      setStats(data.stats);
    } catch {
      setGroups({});
      setStats({});
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProposals();
  }, [loadProposals]);

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectPage = (page: string) => {
    const ids = groups[page]?.map(p => p.id) || [];
    setSelected(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.add(id));
      return next;
    });
  };

  const approveSelected = async () => {
    if (selected.size === 0) return;
    setActionLoading(true);
    try {
      await api.dream.batchApprove(Array.from(selected));
      setSelected(new Set());
      loadProposals();
      addToast('success', `Approved ${selected.size} proposal${selected.size > 1 ? 's' : ''}`);
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleApply = async () => {
    setShowApplyConfirm(false);
    setActionLoading(true);
    try {
      const result = await api.dream.apply(undefined, currentWikiId || undefined);
      loadProposals();
      addToast('success', `Applied ${result.applied} proposal${result.applied !== 1 ? 's' : ''}`);
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleApprove = async (id: string) => {
    try {
      await api.dream.approve(id);
      loadProposals();
      addToast('success', 'Approved');
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  };

  const handleReject = async (id: string) => {
    try {
      await api.dream.reject(id);
      loadProposals();
      addToast('success', 'Rejected');
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  };

  const totalPending = stats.pending || 0;
  const autoApproved = stats.auto_approved || 0;

  if (loading) return <div className="flex items-center justify-center h-full text-muted-foreground">Loading proposals...</div>;
  if (totalPending === 0 && autoApproved === 0) return <EmptyState icon="✱" title="No pending dream proposals" description="AI-generated edit proposals will appear here" />;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {showApplyConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card variant="bordered" className="max-w-sm w-full mx-4">
            <h3 className="text-lg font-bold mb-2 text-foreground">Apply All Approved?</h3>
            <p className="text-sm text-muted-foreground mb-4">
              This will apply all approved proposals to the wiki. This action cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <Button variant="secondary" size="sm" onClick={() => setShowApplyConfirm(false)}>
                Cancel
              </Button>
              <Button variant="primary" size="sm" onClick={handleApply}>
                Apply
              </Button>
            </div>
          </Card>
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-foreground">Dream Proposals</h2>
        <div className="flex gap-2 text-xs">
          <Badge variant="warning">{totalPending} pending</Badge>
          <Badge variant="success">{autoApproved} auto-approved</Badge>
        </div>
      </div>

      <div className="flex gap-2 mb-4">
        <Button variant="success" size="sm" onClick={approveSelected} disabled={selected.size === 0 || actionLoading}>
          Approve Selected ({selected.size})
        </Button>
        <Button variant="primary" size="sm" onClick={() => setShowApplyConfirm(true)} disabled={actionLoading}>
          Apply All Approved
        </Button>
        <Button variant="secondary" size="sm" onClick={loadProposals} disabled={actionLoading}>
          Refresh
        </Button>
      </div>

      <div className="space-y-4">
        {Object.entries(groups).map(([page, proposals]) => (
          <Card key={page} variant="bordered" padding="none">
            <div className="p-3 border-b border-border flex items-center justify-between">
              <span className="text-sm font-semibold text-primary">{page}</span>
              <button onClick={() => selectPage(page)}
                className="text-xs text-muted-foreground hover:text-foreground">
                Select All
              </button>
            </div>
            <div className="divide-y divide-border">
              {proposals.map(p => (
                <div key={p.id} className="p-3">
                  <div className="flex items-center gap-3 mb-2">
                    <input type="checkbox" checked={selected.has(p.id)}
                      onChange={() => toggleSelect(p.id)}
                      className="w-4 h-4 rounded border-border bg-card" />
                    <span className="text-sm text-foreground">{p.edit_type}</span>
                    <span className="text-xs text-muted-foreground">{p.content_length} chars</span>
                    <StatusBadge status={p.status} />
                  </div>
                  <div className="text-xs text-muted-foreground mb-2">{p.reason}</div>
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer hover:text-foreground">Preview content</summary>
                    <pre className="mt-2 p-2 bg-muted rounded overflow-x-auto max-h-32">
                      {p.content.slice(0, 500)}{p.content.length > 500 ? '...' : ''}
                    </pre>
                  </details>
                  {p.status === 'pending' && (
                    <div className="flex gap-2 mt-2">
                      <Button variant="success" size="sm" onClick={() => handleApprove(p.id)}>
                        Approve
                      </Button>
                      <Button variant="danger" size="sm" onClick={() => handleReject(p.id)}>
                        Reject
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variantMap: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    pending: 'warning',
    approved: 'success',
    rejected: 'error',
    auto_approved: 'info',
    applied: 'default',
  };
  return <Badge variant={variantMap[status] || 'default'}>{status}</Badge>;
}