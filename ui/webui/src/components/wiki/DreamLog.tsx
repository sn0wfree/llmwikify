import { useState, useEffect } from 'react';
import { api, DreamEdit } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { EmptyState } from '../agent/StateViews';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';

export function DreamLog() {
  const [edits, setEdits] = useState<DreamEdit[]>([]);
  const [loading, setLoading] = useState(true);
  const { currentWikiId } = useWikiStore();

  useEffect(() => {
    loadEdits();
  }, []);

  const loadEdits = async () => {
    try {
      const log = await api.dream.log(undefined, currentWikiId || undefined);
      setEdits(log);
    } catch {
      setEdits([]);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading dream log...
      </div>
    );
  }

  if (edits.length === 0) {
    return <EmptyState icon="✦" title="No dream edits recorded" description="Dream mode edits will appear here" />;
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-foreground">Dream Edit Log</h2>
        <Button variant="secondary" size="sm" onClick={loadEdits}>
          Refresh
        </Button>
      </div>

      {edits.length === 0 ? null : (
        <div className="space-y-4">
          {edits.map((edit, i) => (
            <Card key={i} variant="bordered" padding="none">
              <div className="p-3 border-b border-border flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">
                  {formatTime(edit.timestamp)}
                </span>
                <div className="flex gap-3 text-xs">
                  <span className="text-muted-foreground">
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
                      <span className="text-sm text-primary">{e.page}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">
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
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variantMap: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    updated: 'info',
    created: 'success',
    no_changes: 'default',
  };
  return <Badge variant={variantMap[status] || 'default'}>{status}</Badge>;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}