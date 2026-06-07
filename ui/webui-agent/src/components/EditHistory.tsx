import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { EmptyState } from './StateViews';
import { Card } from './ui/Card';
import { Button } from './ui/Button';

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
  const { currentWikiId } = useAgentWikiStore();

  const loadHistory = useCallback(async () => {
    try {
      const status = await api.agent.status(currentWikiId || undefined);
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

  if (loading) return <div className="flex items-center justify-center h-full text-[var(--text-secondary)]">Loading edit history...</div>;
  if (edits.length === 0) return <EmptyState icon="✎" title="No edit history" description="Agent edit operations will appear here" />;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-[var(--text-primary)]">Edit History</h2>
        <Button variant="secondary" size="sm" onClick={loadHistory}>
          Refresh
        </Button>
      </div>

      <div className="space-y-2">
        {edits.map((edit, i) => (
          <Card key={i} variant="bordered" padding="md">
            <div className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full ${edit.success ? 'bg-green-400' : 'bg-red-400'}`} />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-[var(--text-primary)]">{edit.tool}</div>
                <div className="text-xs text-[var(--text-secondary)]">
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