import { useEffect, useState, useCallback } from 'react';
import {
  Wrench, RefreshCw, Loader2, CheckCircle2, AlertCircle,
  Database, FileSearch, Zap, Clock, FileCheck, FileX,
} from 'lucide-react';
import { api } from '../../api';
import { cn } from '@/lib/utils';

interface MaintenanceStatus {
  running: boolean;
  config: {
    enabled: boolean;
    auto_ingest: { enabled: boolean; write_mode: string; max_backlog_per_start: number };
    gap_filler: { enabled: boolean; max_per_cycle: number; min_priority: number };
    llm_rate_limit: { enabled: boolean; max_requests: number; window_seconds: number };
    lint_interval_seconds: number;
    gaps_interval_seconds: number;
    db_maintenance_interval_seconds: number;
  };
  llm_rate_limit: { enabled: boolean; max_requests: number; window_seconds: number; throttled_total: number; window_in_use: number };
  auto_ingest: Record<string, {
    wiki_id: string;
    watching: boolean;
    raw_dir: string;
    events: number;
    ingested: number;
    pages_written: number;
    failed: number;
    fallback_proposals: number;
    backlog_replayed: number;
    backlog_deferred: number;
    last_ingest_at: number | null;
    last_error: string | null;
  }>;
  gap_filler: Record<string, {
    wiki_id: string;
    last_cycle: {
      detected: number;
      processed: number;
      mechanical_fixes: number;
      proposals_created: number;
      skipped_low_priority: number;
      errors: number;
      ran_at: number;
    } | null;
  }>;
  last_db_maintenance_at: number | null;
}

export function MaintenancePanel() {
  const [status, setStatus] = useState<MaintenanceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await api.maintenance.status() as unknown as MaintenanceStatus;
      setStatus(s);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleTrigger = useCallback(async (task: string) => {
    setTriggering(task);
    setError(null);
    try {
      await api.maintenance.trigger(task as 'gaps' | 'db' | 'all');
      await loadStatus();
    } catch (e) {
      setError(String(e));
    } finally {
      setTriggering(null);
    }
  }, [loadStatus]);

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading maintenance status…</span>
        </div>
      </div>
    );
  }

  if (error && !status) {
    return (
      <div className="p-6">
        <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/20 text-sm text-destructive">
          {error}
        </div>
      </div>
    );
  }

  const rateLimit = status?.llm_rate_limit;
  const autoIngestEntries = Object.values(status?.auto_ingest || {});
  const gapFillerEntries = Object.values(status?.gap_filler || {});
  const totalIngested = autoIngestEntries.reduce((s, e) => s + (e.ingested || 0), 0);
  const totalPagesWritten = autoIngestEntries.reduce((s, e) => s + (e.pages_written || 0), 0);
  const totalFallback = autoIngestEntries.reduce((s, e) => s + (e.fallback_proposals || 0), 0);
  const totalFailed = autoIngestEntries.reduce((s, e) => s + (e.failed || 0), 0);

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="w-5 h-5 text-primary" />
          <h2 className="text-lg font-semibold">Self-Maintenance</h2>
        </div>
        <button
          onClick={loadStatus}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-secondary hover:bg-secondary/80 transition-colors"
        >
          <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Overall Status */}
      <div className="flex items-center gap-3 p-3 rounded-lg bg-card border">
        <div className={cn(
          'w-2.5 h-2.5 rounded-full',
          status?.running ? 'bg-emerald-500' : 'bg-red-500',
        )} />
        <span className="text-sm font-medium">
          {status?.running ? 'Maintenance running' : 'Maintenance stopped'}
        </span>
        <span className="text-xs text-muted-foreground ml-auto">
          LLM budget: {rateLimit?.max_requests ?? '–'} units / {rateLimit?.window_seconds ?? '–'}s
        </span>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Cards Grid */}
      <div className="grid grid-cols-2 gap-4">
        {/* Auto Ingest */}
        <div className="p-4 rounded-lg bg-card border space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <FileSearch className="w-4 h-4 text-blue-400" />
            <span>Auto Ingest</span>
            {autoIngestEntries.map((e) => (
              <span key={e.wiki_id} className={cn(
                'ml-auto text-[10px] px-1.5 py-0.5 rounded-full',
                e.watching ? 'bg-emerald-500/20 text-emerald-400' : 'bg-gray-500/20 text-gray-400',
              )}>
                {e.watching ? 'watching' : 'off'}
              </span>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat label="Ingested" value={totalIngested} />
            <Stat label="Pages Written" value={totalPagesWritten} />
            <Stat label="Fallback" value={totalFallback} />
          </div>
          {totalFailed > 0 && (
            <div className="flex items-center gap-1 text-[10px] text-amber-400">
              <AlertCircle className="w-3 h-3" />
              {totalFailed} failed
            </div>
          )}
        </div>

        {/* Gap Filler */}
        <div className="p-4 rounded-lg bg-card border space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Zap className="w-4 h-4 text-purple-400" />
            <span>Gap Filler</span>
          </div>
          {gapFillerEntries.length === 0 ? (
            <p className="text-xs text-muted-foreground">No wikis</p>
          ) : gapFillerEntries.map((gf) => {
            const lc = gf.last_cycle;
            return (
              <div key={gf.wiki_id} className="text-xs space-y-1">
                <div className="text-muted-foreground">{gf.wiki_id}</div>
                {lc ? (
                  <div className="flex gap-2 text-muted-foreground">
                    <span>detected: {lc.detected}</span>
                    <span>processed: {lc.processed}</span>
                    <span>fixes: {lc.mechanical_fixes}</span>
                    <span>proposals: {lc.proposals_created}</span>
                  </div>
                ) : (
                  <span className="text-muted-foreground">No cycles yet</span>
                )}
              </div>
            );
          })}
        </div>

        {/* Rate Limiter */}
        <div className="p-4 rounded-lg bg-card border space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Clock className="w-4 h-4 text-amber-400" />
            <span>LLM Rate Limit</span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
            <div>Max: {rateLimit?.max_requests ?? '–'}</div>
            <div>Window: {rateLimit?.window_seconds ?? '–'}s</div>
            <div>Throttled: {rateLimit?.throttled_total ?? 0}</div>
            <div>In use: {rateLimit?.window_in_use ?? 0}</div>
          </div>
        </div>

        {/* DB Maintenance */}
        <div className="p-4 rounded-lg bg-card border space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Database className="w-4 h-4 text-cyan-400" />
            <span>DB Maintenance</span>
          </div>
          <div className="text-xs text-muted-foreground">
            {status?.last_db_maintenance_at
              ? `Last run: ${new Date(status.last_db_maintenance_at * 1000).toLocaleString()}`
              : 'Not yet run'}
          </div>
          <div className="text-xs text-muted-foreground">
            Interval: {(status?.config.db_maintenance_interval_seconds ?? 0) / 3600}h
          </div>
        </div>
      </div>

      {/* Alert Banner */}
      {totalFallback > 0 && (
        <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
          <span className="text-sm text-amber-300">
            {totalFallback} file(s) fell back to proposals. Review in the proposals section below.
          </span>
        </div>
      )}

      {/* Trigger Buttons */}
      <div className="flex gap-2">
        {['lint', 'gaps', 'db', 'all'].map((task) => (
          <button
            key={task}
            onClick={() => handleTrigger(task)}
            disabled={triggering !== null}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-50"
          >
            {triggering === task && <Loader2 className="w-3 h-3 animate-spin" />}
            {task === 'all' ? 'Run All' : `Trigger ${task}`}
          </button>
        ))}
      </div>

      {/* Proposals Section */}
      <ProposalsSection />
    </div>
  );
}

function ProposalsSection() {
  const [proposals, setProposals] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [acting, setActing] = useState(false);

  const loadProposals = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetch('/api/maintenance/proposals?status=pending').then(r => r.json());
      setProposals(result.proposals || []);
    } catch { setProposals([]); } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadProposals(); }, [loadProposals]);

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleBatchApprove = async () => {
    if (selected.size === 0) return;
    setActing(true);
    try {
      await fetch('/api/maintenance/proposals/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(selected) }),
      });
      setSelected(new Set());
      await loadProposals();
    } finally { setActing(false); }
  };

  const handleBatchReject = async () => {
    if (selected.size === 0) return;
    setActing(true);
    try {
      await fetch('/api/maintenance/proposals/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(selected) }),
      });
      setSelected(new Set());
      await loadProposals();
    } finally { setActing(false); }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Pending Proposals ({proposals.length})</h3>
        <div className="flex gap-2">
          <button
            onClick={handleBatchApprove}
            disabled={selected.size === 0 || acting}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            <FileCheck className="w-3 h-3" />
            Approve ({selected.size})
          </button>
          <button
            onClick={handleBatchReject}
            disabled={selected.size === 0 || acting}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-50"
          >
            <FileX className="w-3 h-3" />
            Reject ({selected.size})
          </button>
          <button onClick={loadProposals} className="p-1 rounded text-xs text-muted-foreground hover:bg-white/[0.06]">
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-xs text-muted-foreground flex items-center gap-1">
          <Loader2 className="w-3 h-3 animate-spin" /> Loading…
        </div>
      ) : proposals.length === 0 ? (
        <div className="text-xs text-muted-foreground py-2">No pending proposals</div>
      ) : (
        <div className="space-y-1 max-h-60 overflow-y-auto">
          {proposals.map((p) => (
            <label
              key={p.id as string}
              className="flex items-start gap-2 p-2 rounded bg-card border cursor-pointer hover:bg-white/[0.02]"
            >
              <input
                type="checkbox"
                checked={selected.has(p.id as string)}
                onChange={() => toggleSelect(p.id as string)}
                className="mt-0.5 shrink-0"
              />
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium truncate">{p.page_name as string}</div>
                <div className="text-[10px] text-muted-foreground truncate">
                  {p.edit_type as string} · {(p.content_length as number) ?? 0} chars · {p.reason as string}
                </div>
              </div>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
    </div>
  );
}
