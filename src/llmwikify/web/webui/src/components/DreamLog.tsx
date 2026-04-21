import { useState, useEffect } from 'react';
import { api, DreamEdit } from '../api';

export function DreamLog() {
  const [edits, setEdits] = useState<DreamEdit[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadEdits();
  }, []);

  const loadEdits = async () => {
    try {
      const log = await api.dream.log();
      setEdits(log);
    } catch {
      setEdits([]);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Loading dream log...
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Dream Edit Log</h2>
        <button
          onClick={loadEdits}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded"
        >
          Refresh
        </button>
      </div>

      {edits.length === 0 ? (
        <p className="text-slate-500 text-sm">No dream edits recorded yet.</p>
      ) : (
        <div className="space-y-4">
          {edits.map((edit, i) => (
            <div key={i} className="bg-slate-800 rounded border border-slate-700">
              <div className="p-3 border-b border-slate-700 flex items-center justify-between">
                <span className="text-sm font-medium">
                  {formatTime(edit.timestamp)}
                </span>
                <div className="flex gap-3 text-xs">
                  <span className="text-slate-400">
                    {edit.sinks_processed} sinks
                  </span>
                  <span className="text-green-400">
                    {edit.edits_applied} edits
                  </span>
                </div>
              </div>
              {edit.edits.length > 0 && (
                <div className="p-3">
                  {edit.edits.map((e, j) => (
                    <div key={j} className="flex items-center justify-between py-1">
                      <span className="text-sm text-blue-400">{e.page}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-400">
                          {e.edit_count} changes
                        </span>
                        <StatusBadge status={e.status} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {edit.errors.length > 0 && (
                <div className="p-3 bg-red-500/10 border-t border-red-500/20">
                  {edit.errors.map((err, j) => (
                    <div key={j} className="text-sm text-red-400">
                      Error: {err.page} - {err.error}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    updated: 'bg-blue-500/20 text-blue-400',
    created: 'bg-green-500/20 text-green-400',
    no_changes: 'bg-slate-500/20 text-slate-400',
  };
  return (
    <span className={`px-1.5 py-0.5 text-xs rounded ${colors[status] || colors.no_changes}`}>
      {status}
    </span>
  );
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
