import { useState, useEffect, useCallback } from 'react';
import { api, IngestLogEntry } from '../api';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { EmptyState } from './StateViews';
import { Card } from './ui/Card';
import { Button } from './ui/Button';
import { Badge } from './ui/Badge';

export function IngestLog() {
  const [entries, setEntries] = useState<IngestLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const { currentWikiId } = useAgentWikiStore();

  const loadLog = useCallback(async () => {
    try {
      const data = await api.ingest.log(undefined, currentWikiId || undefined);
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

  if (loading) return <div className="flex items-center justify-center h-full text-[var(--text-secondary)]">Loading ingest log...</div>;
  if (entries.length === 0) return <EmptyState icon="↓" title="No ingest records" description="Content ingestion history will appear here" />;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-[var(--text-primary)]">Ingest History</h2>
        <Button variant="secondary" size="sm" onClick={loadLog}>
          Refresh
        </Button>
      </div>

      <div className="space-y-3">
        {entries.map(entry => (
          <Card key={entry.id} variant="bordered" padding="md">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-[var(--accent)]">
                {String(entry.arguments?.source || entry.tool)}
              </span>
              <span className="text-xs text-[var(--text-secondary)]">
                {formatTime(entry.timestamp)}
              </span>
            </div>
            <div className="text-xs text-[var(--text-secondary)] mb-2">
              {String(entry.result_summary).slice(0, 200)}
              {String(entry.result_summary).length > 200 ? '...' : ''}
            </div>
            <div className="flex gap-2">
              <Badge variant="success">{entry.status}</Badge>
              <Button variant="danger" size="sm" onClick={() => api.ingest.revert(entry.id)}>
                Revert (requires git)
              </Button>
            </div>
          </Card>
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