import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

interface EditEntry {
  tool: string;
  success: boolean;
  error: string | null;
  confirmation_id: string | null;
  timestamp: string;
}

export function EditHistory() {
  const [edits, setEdits] = useState<EditEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const loadHistory = useCallback(async () => {
    try {
      const status = await api.agent.status();
      setEdits((status.action_log || []) as EditEntry[]);
    } catch {
      setEdits([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  if (loading) return <div className="flex items-center justify-center h-full text-slate-500">Loading edit history...</div>;
  if (edits.length === 0) return <div className="p-6 text-slate-500">No edit history.</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Edit History</h2>
        <button onClick={loadHistory}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded">
          Refresh
        </button>
      </div>

      <div className="space-y-2">
        {edits.map((edit, i) => (
          <div key={i} className="bg-slate-800 rounded border border-slate-700 p-3 flex items-center gap-3">
            <div className={`w-2 h-2 rounded-full ${edit.success ? 'bg-green-400' : 'bg-red-400'}`} />
            <div className="flex-1 min-w-0">
              <div className="text-sm text-slate-300">{edit.tool}</div>
              <div className="text-xs text-slate-500">
                {formatTime(edit.timestamp)}
                {edit.confirmation_id && ` · ID: ${edit.confirmation_id}`}
              </div>
            </div>
            {edit.error && (
              <span className="text-xs text-red-400 truncate max-w-xs" title={edit.error}>
                {edit.error}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
