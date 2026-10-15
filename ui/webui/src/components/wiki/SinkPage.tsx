import { useState, useEffect, useCallback } from 'react';
import { Database, AlertTriangle, Activity, RefreshCw } from 'lucide-react';
import { api, SinkStatus } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { LoadingState, EmptyState } from '../ui/states';
import { cn } from '@/lib/utils';

const URGENCY_COLORS: Record<string, string> = {
  ok: 'bg-success/15 text-success border-success/30',
  attention: 'bg-warning/15 text-warning border-warning/30',
  aging: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  stale: 'bg-destructive/15 text-destructive border-destructive/30',
};

const URGENCY_LABELS: Record<string, string> = {
  ok: 'OK',
  attention: 'Attention',
  aging: 'Aging',
  stale: 'Stale',
};

export function SinkPage() {
  const [sinkStatus, setSinkStatus] = useState<SinkStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  const { currentWikiId, isMultiWikiMode } = useWikiStore();

  const loadData = useCallback(async () => {
    try {
      let status: SinkStatus | null;
      if (isMultiWikiMode && currentWikiId) {
        status = await api.wiki.scoped.sinkStatus(currentWikiId);
      } else {
        status = await api.wiki.sinkStatus();
      }
      setSinkStatus(status);
    } catch {
      setSinkStatus(null);
    } finally {
      setLoading(false);
    }
  }, [currentWikiId, isMultiWikiMode]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  if (loading) return <LoadingState message="Loading sink data…" />;
  if (!sinkStatus || sinkStatus.total_sinks === 0) {
    return <EmptyState icon={<Database className="w-6 h-6" />} title="No sinks" description="Sinks are deprecation markers for outdated wiki pages." />;
  }

  const filteredSinks = filter === 'all'
    ? sinkStatus.sinks
    : sinkStatus.sinks.filter((s) => s.urgency === filter);

  return (
    <div className="overflow-y-auto h-full">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-end justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-foreground tracking-tight">Sink Overview</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Pages marked for deprecation — review and consolidate entries
            </p>
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium',
              'glass hover:bg-white/[0.04] text-foreground/85 transition-colors',
            )}
          >
            <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            <span>Refresh</span>
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
          <div className="rounded-xl glass p-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.1em]">Total Sinks</span>
              <div className="w-6 h-6 rounded-md flex items-center justify-center bg-foreground/5 text-foreground/80"><Activity className="w-3.5 h-3.5" /></div>
            </div>
            <div className="text-2xl font-bold text-foreground tabular-nums">{sinkStatus.total_sinks}</div>
          </div>
          <div className="rounded-xl glass p-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.1em]">Total Entries</span>
              <div className="w-6 h-6 rounded-md flex items-center justify-center bg-foreground/5 text-foreground/80"><Database className="w-3.5 h-3.5" /></div>
            </div>
            <div className="text-2xl font-bold text-foreground tabular-nums">{sinkStatus.total_entries}</div>
          </div>
          <div className="rounded-xl glass p-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.1em]">Urgent</span>
              <div className="w-6 h-6 rounded-md flex items-center justify-center bg-destructive/10 text-destructive"><AlertTriangle className="w-3.5 h-3.5" /></div>
            </div>
            <div className="text-2xl font-bold text-foreground tabular-nums">{sinkStatus.urgent_count}</div>
          </div>
        </div>

        <div className="rounded-xl glass overflow-hidden">
          <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Sinks</h2>
            <div className="flex items-center gap-1">
              {['all', 'ok', 'attention', 'aging', 'stale'].map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={cn(
                    'px-2 py-0.5 text-[10px] font-medium rounded transition-colors',
                    filter === f
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {f === 'all' ? 'All' : URGENCY_LABELS[f] || f}
                </button>
              ))}
            </div>
          </div>
          <div className="divide-y divide-border/30">
            {filteredSinks.map((s) => {
              const urgencyColor = URGENCY_COLORS[s.urgency] || URGENCY_COLORS.ok;
              return (
                <div key={s.page_name} className="px-4 py-3 flex items-center gap-3 hover:bg-white/[0.02] transition-colors">
                  <span className="text-sm text-foreground flex-1 truncate">{s.page_name}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">{s.entry_count} entries</span>
                  <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium border', urgencyColor)}>
                    {URGENCY_LABELS[s.urgency] || s.urgency}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
