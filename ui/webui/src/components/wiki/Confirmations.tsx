import { useState, useEffect, useCallback } from 'react';
import { api, Confirmation } from '../../api';
import { useToast } from './Toast';
import { useWikiStore } from '../../stores/wikiStore';
import { EmptyState } from '../agent/StateViews';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { ConfirmationModal } from '../agent/ConfirmationModal';

export function Confirmations() {
  const [groups, setGroups] = useState<Record<string, Confirmation[]>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [detailConfirmation, setDetailConfirmation] = useState<Confirmation | null>(null);
  const { addToast } = useToast();
  const { currentWikiId } = useWikiStore();

  const loadConfirmations = useCallback(async () => {
    try {
      const data = await api.confirmations.list(currentWikiId || undefined);
      setGroups(data);
    } catch {
      setGroups({});
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfirmations();
  }, [loadConfirmations]);

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectGroup = (group: string) => {
    const ids = groups[group]?.map(c => c.id) || [];
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
      const count = selected.size;
      await api.confirmations.batchApprove(Array.from(selected), currentWikiId || undefined);
      setSelected(new Set());
      loadConfirmations();
      addToast('success', `Approved ${count} confirmation${count > 1 ? 's' : ''}`);
    } catch (e) {
      addToast('error', `Failed to approve: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setActionLoading(false);
    }
  };

  const rejectSelected = async () => {
    if (selected.size === 0) return;
    setActionLoading(true);
    try {
      const ids = Array.from(selected);
      for (const id of ids) {
        await api.confirmations.reject(id, currentWikiId || undefined);
      }
      setSelected(new Set());
      loadConfirmations();
      addToast('success', `Rejected ${ids.length} confirmation${ids.length > 1 ? 's' : ''}`);
    } catch (e) {
      addToast('error', `Failed to reject: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleApprove = async (id: string, editedArgs?: Record<string, unknown>) => {
    try {
      await api.confirmations.approve(id, currentWikiId || undefined, editedArgs);
      loadConfirmations();
      addToast('success', 'Approved');
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  };

  const handleReject = async (id: string) => {
    try {
      await api.confirmations.reject(id, currentWikiId || undefined);
      loadConfirmations();
      addToast('success', 'Rejected');
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  };

  const totalPending = Object.values(groups).reduce((sum, arr) => sum + arr.length, 0);

  if (loading) return <div className="flex items-center justify-center h-full text-muted-foreground">Loading confirmations...</div>;
  if (totalPending === 0) return <EmptyState icon="✓" title="No pending confirmations" description="Agent operations requiring approval will appear here" />;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-foreground">Pending Confirmations ({totalPending})</h2>
        <div className="flex gap-2">
          <Button variant="success" size="sm" onClick={approveSelected} disabled={selected.size === 0 || actionLoading}>
            Approve Selected ({selected.size})
          </Button>
          <Button variant="danger" size="sm" onClick={rejectSelected} disabled={selected.size === 0 || actionLoading}>
            Reject Selected
          </Button>
          <Button variant="secondary" size="sm" onClick={loadConfirmations} disabled={actionLoading}>
            Refresh
          </Button>
        </div>
      </div>

      <div className="space-y-4">
        {Object.entries(groups).map(([group, confirmations]) => (
          <Card key={group} variant="bordered" padding="none">
            <div className="p-3 border-b border-border flex items-center justify-between">
              <span className="text-sm font-semibold text-foreground capitalize">
                {group.replace(/_/g, ' ')} ({confirmations.length})
              </span>
              <button onClick={() => selectGroup(group)}
                className="text-xs text-primary hover:text-[var(--accent-hover)]">
                Select All
              </button>
            </div>
            <div className="divide-y divide-border">
              {confirmations.map(c => (
                <div key={c.id}
                  className="p-3 flex items-center gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => setDetailConfirmation(c)}
                >
                  <input type="checkbox" checked={selected.has(c.id)}
                    onChange={() => toggleSelect(c.id)}
                    onClick={e => e.stopPropagation()}
                    className="w-4 h-4 rounded border-border bg-card" />
                  <div className="flex-1 min-w-0 confirm-row-content">
                    <div className="text-sm text-primary">{c.tool}</div>
                    <div className="text-xs text-muted-foreground">
                      {String(c.impact?.page || c.impact?.source || 'N/A')}
                      {' · '}
                      {c.impact?.chars ? `${c.impact.chars} chars` : String(c.impact?.change_type || '')}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="success" size="sm" onClick={(e) => { e.stopPropagation(); handleApprove(c.id); }}>
                      Approve
                    </Button>
                    <Button variant="danger" size="sm" onClick={(e) => { e.stopPropagation(); handleReject(c.id); }}>
                      Reject
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>

      {detailConfirmation && (
        <ConfirmationModal
          confirmationId={detailConfirmation.id}
          tool={detailConfirmation.tool}
          args={detailConfirmation.arguments}
          impact={detailConfirmation.impact}
          group={detailConfirmation.group}
          createdAt={detailConfirmation.created_at}
          onApprove={(editedArgs) => { handleApprove(detailConfirmation.id, editedArgs); setDetailConfirmation(null); }}
          onReject={() => { handleReject(detailConfirmation.id); setDetailConfirmation(null); }}
          loading={actionLoading}
        />
      )}
    </div>
  );
}