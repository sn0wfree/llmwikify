import { useEffect, useState } from 'react';
import { RefreshCw, FileText, CheckCircle2, Circle, AlertTriangle, Loader2 } from 'lucide-react';
import { api, ResearchRunStatus } from '../../api';
import { cn } from '@/lib/utils';

interface ResearchRunCardProps {
  initial: ResearchRunStatus;
}

const TERMINAL = new Set(['ok', 'complete', 'failed', 'partial', 'halted']);

function marker(status: string) {
  if (status === 'complete') return <CheckCircle2 className="w-4 h-4 text-success" />;
  if (status === 'failed') return <AlertTriangle className="w-4 h-4 text-destructive" />;
  if (status === 'running') return <Loader2 className="w-4 h-4 text-primary animate-spin" />;
  return <Circle className="w-4 h-4 text-muted-foreground/50" />;
}

export function ResearchRunCard({ initial }: ResearchRunCardProps) {
  const [run, setRun] = useState<ResearchRunStatus>(initial);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    if (!run.run_id) return;
    setLoading(true);
    try {
      const next = await api.agent.getResearchRun(run.run_id);
      setRun(next);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!run.run_id || TERMINAL.has(run.status)) return;
    const id = window.setInterval(() => {
      void refresh();
    }, 3000);
    return () => window.clearInterval(id);
  }, [run.run_id, run.status]);

  const counts = run.artifact_counts || {};

  return (
    <div className="ml-9 max-w-2xl rounded-xl border border-primary/20 bg-card/80 shadow-soft overflow-hidden">
      <div className="px-4 py-3 border-b border-border/60 bg-primary/5 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-foreground flex items-center gap-2">
            <FileText className="w-4 h-4 text-primary" />
            AutoResearch
          </div>
          <div className="text-xs text-muted-foreground font-mono truncate">{run.run_id}</div>
        </div>
        <div className={cn(
          'px-2 py-1 rounded-full text-xs border',
          run.status === 'failed'
            ? 'text-destructive border-destructive/30 bg-destructive/10'
            : TERMINAL.has(run.status)
              ? 'text-success border-success/30 bg-success/10'
              : 'text-primary border-primary/30 bg-primary/10'
        )}>
          {run.status}
        </div>
      </div>

      <div className="p-4 space-y-4">
        <div className="space-y-2">
          {(run.timeline || []).map((item) => (
            <div key={item.phase_id} className="flex items-center gap-3 text-sm">
              {marker(item.status)}
              <span className="w-32 text-foreground">{item.label || item.phase_id}</span>
              <span className="text-xs text-muted-foreground">{item.status}</span>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-lg bg-muted/60 p-2">
            <div className="text-muted-foreground">Evidence</div>
            <div className="text-lg font-semibold text-foreground">{counts.evidence_items || 0}</div>
          </div>
          <div className="rounded-lg bg-muted/60 p-2">
            <div className="text-muted-foreground">Findings</div>
            <div className="text-lg font-semibold text-foreground">{counts.findings || 0}</div>
          </div>
          <div className="rounded-lg bg-muted/60 p-2">
            <div className="text-muted-foreground">Proposals</div>
            <div className="text-lg font-semibold text-foreground">{counts.wiki_update_proposals || 0}</div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>不写入 Wiki；完成后生成 proposals。</span>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-border hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
            刷新状态
          </button>
        </div>
      </div>
    </div>
  );
}
