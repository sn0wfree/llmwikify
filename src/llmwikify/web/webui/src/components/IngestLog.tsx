import { useState, useEffect, useCallback } from 'react';
import { api, IngestLogEntry } from '../api';

export function IngestLog() {
  const [entries, setEntries] = useState<IngestLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const loadLog = useCallback(async () => {
    try {
      const data = await api.ingest.log();
      setEntries(data);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLog();
  }, [loadLog]);

  if (loading) return <div className="flex items-center justify-center h-full text-slate-500">Loading ingest log...</div>;
  if (entries.length === 0) return <div className="p-6 text-slate-500">No ingest records.</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Ingest History</h2>
        <button onClick={loadLog}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded">
          Refresh
        </button>
      </div>

      <div className="space-y-3">
        {entries.map(entry => (
          <div key={entry.id} className="bg-slate-800 rounded border border-slate-700 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-blue-400">
                {String(entry.arguments?.source || entry.tool)}
              </span>
              <span className="text-xs text-slate-500">
                {formatTime(entry.timestamp)}
              </span>
            </div>
            <div className="text-xs text-slate-400 mb-2">
              {String(entry.result_summary).slice(0, 200)}
              {String(entry.result_summary).length > 200 ? '...' : ''}
            </div>
            <div className="flex gap-2">
              <span className="px-2 py-0.5 text-xs bg-green-500/20 text-green-400 rounded">
                {entry.status}
              </span>
              <button
                onClick={() => api.ingest.revert(entry.id)}
                className="px-2 py-0.5 text-xs bg-red-600/20 text-red-400 rounded hover:bg-red-600/30">
                Revert (requires git)
              </button>
            </div>
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
