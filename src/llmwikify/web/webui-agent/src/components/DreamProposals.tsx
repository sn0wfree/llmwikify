import { useState, useEffect, useCallback } from 'react';
import { api, DreamProposal } from '../api';
import { useToast } from './Toast';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { EmptyState } from './StateViews';

export function DreamProposals() {
  const [groups, setGroups] = useState<Record<string, DreamProposal[]>>({});
  const [stats, setStats] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [showApplyConfirm, setShowApplyConfirm] = useState(false);
  const { addToast } = useToast();
  const { currentWikiId } = useAgentWikiStore();

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
      const result = await api.dream.apply();
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

  if (loading) return <div className="flex items-center justify-center h-full text-slate-500">Loading proposals...</div>;
  if (totalPending === 0 && autoApproved === 0) return <EmptyState icon="✱" title="No pending dream proposals" description="AI-generated edit proposals will appear here" />;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {showApplyConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-bold mb-2">Apply All Approved?</h3>
            <p className="text-sm text-slate-400 mb-4">
              This will apply all approved proposals to the wiki. This action cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowApplyConfirm(false)}
                className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded">
                Cancel
              </button>
              <button onClick={handleApply}
                className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 rounded text-white">
                Apply
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Dream Proposals</h2>
        <div className="flex gap-2 text-xs">
          <span className="px-2 py-1 bg-yellow-500/20 text-yellow-400 rounded">{totalPending} pending</span>
          <span className="px-2 py-1 bg-green-500/20 text-green-400 rounded">{autoApproved} auto-approved</span>
        </div>
      </div>

      <div className="flex gap-2 mb-4">
        <button onClick={approveSelected} disabled={selected.size === 0 || actionLoading}
          className="px-3 py-1.5 text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded text-white">
          Approve Selected ({selected.size})
        </button>
        <button onClick={() => setShowApplyConfirm(true)} disabled={actionLoading}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-white">
          Apply All Approved
        </button>
        <button onClick={loadProposals} disabled={actionLoading}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded disabled:opacity-50">
          Refresh
        </button>
      </div>

      <div className="space-y-4">
        {Object.entries(groups).map(([page, proposals]) => (
          <div key={page} className="bg-slate-800 rounded border border-slate-700">
            <div className="p-3 border-b border-slate-700 flex items-center justify-between">
              <span className="text-sm font-semibold text-blue-400">{page}</span>
              <button onClick={() => selectPage(page)}
                className="text-xs text-slate-400 hover:text-slate-300">
                Select All
              </button>
            </div>
            <div className="divide-y divide-slate-700">
              {proposals.map(p => (
                <div key={p.id} className="p-3">
                  <div className="flex items-center gap-3 mb-2">
                    <input type="checkbox" checked={selected.has(p.id)}
                      onChange={() => toggleSelect(p.id)}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-700" />
                    <span className="text-sm text-slate-300">{p.edit_type}</span>
                    <span className="text-xs text-slate-500">{p.content_length} chars</span>
                    <StatusBadge status={p.status} />
                  </div>
                  <div className="text-xs text-slate-400 mb-2">{p.reason}</div>
                  <details className="text-xs text-slate-500">
                    <summary className="cursor-pointer hover:text-slate-400">Preview content</summary>
                    <pre className="mt-2 p-2 bg-slate-900 rounded overflow-x-auto max-h-32">
                      {p.content.slice(0, 500)}{p.content.length > 500 ? '...' : ''}
                    </pre>
                  </details>
                  {p.status === 'pending' && (
                    <div className="flex gap-2 mt-2">
                      <button onClick={() => handleApprove(p.id)}
                        className="px-2 py-1 text-xs bg-green-600/20 text-green-400 rounded hover:bg-green-600/30">
                        Approve
                      </button>
                      <button onClick={() => handleReject(p.id)}
                        className="px-2 py-1 text-xs bg-red-600/20 text-red-400 rounded hover:bg-red-600/30">
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-500/20 text-yellow-400',
    approved: 'bg-green-500/20 text-green-400',
    rejected: 'bg-red-500/20 text-red-400',
    auto_approved: 'bg-blue-500/20 text-blue-400',
    applied: 'bg-slate-500/20 text-slate-400',
  };
  return (
    <span className={`px-1.5 py-0.5 text-xs rounded ${colors[status] || colors.pending}`}>
      {status}
    </span>
  );
}