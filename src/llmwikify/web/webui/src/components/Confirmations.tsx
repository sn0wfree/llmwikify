import { useState, useEffect, useCallback } from 'react';
import { api, Confirmation } from '../api';

export function Confirmations() {
  const [groups, setGroups] = useState<Record<string, Confirmation[]>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  const loadConfirmations = useCallback(async () => {
    try {
      const data = await api.confirmations.list();
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
    await api.confirmations.batchApprove(Array.from(selected));
    setSelected(new Set());
    loadConfirmations();
  };

  const rejectSelected = async () => {
    if (selected.size === 0) return;
    for (const id of selected) {
      await api.confirmations.reject(id);
    }
    setSelected(new Set());
    loadConfirmations();
  };

  const totalPending = Object.values(groups).reduce((sum, arr) => sum + arr.length, 0);

  if (loading) return <div className="flex items-center justify-center h-full text-slate-500">Loading confirmations...</div>;
  if (totalPending === 0) return <div className="p-6 text-slate-500">No pending confirmations.</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Pending Confirmations ({totalPending})</h2>
        <div className="flex gap-2">
          <button onClick={approveSelected} disabled={selected.size === 0}
            className="px-3 py-1.5 text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded text-white">
            Approve Selected ({selected.size})
          </button>
          <button onClick={rejectSelected} disabled={selected.size === 0}
            className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 rounded text-white">
            Reject Selected
          </button>
          <button onClick={loadConfirmations}
            className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded">
            Refresh
          </button>
        </div>
      </div>

      <div className="space-y-4">
        {Object.entries(groups).map(([group, confirmations]) => (
          <div key={group} className="bg-slate-800 rounded border border-slate-700">
            <div className="p-3 border-b border-slate-700 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-300 capitalize">
                {group.replace(/_/g, ' ')} ({confirmations.length})
              </span>
              <button onClick={() => selectGroup(group)}
                className="text-xs text-blue-400 hover:text-blue-300">
                Select All
              </button>
            </div>
            <div className="divide-y divide-slate-700">
              {confirmations.map(c => (
                <div key={c.id} className="p-3 flex items-center gap-3">
                  <input type="checkbox" checked={selected.has(c.id)}
                    onChange={() => toggleSelect(c.id)}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-700" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-blue-400">{c.tool}</div>
                    <div className="text-xs text-slate-500">
                      {String(c.impact?.page || c.impact?.source || 'N/A')}
                      {' · '}
                      {c.impact?.chars ? `${c.impact.chars} chars` : String(c.impact?.change_type || '')}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => api.confirmations.approve(c.id).then(loadConfirmations)}
                      className="px-2 py-1 text-xs bg-green-600/20 text-green-400 rounded hover:bg-green-600/30">
                      Approve
                    </button>
                    <button onClick={() => api.confirmations.reject(c.id).then(loadConfirmations)}
                      className="px-2 py-1 text-xs bg-red-600/20 text-red-400 rounded hover:bg-red-600/30">
                      Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
