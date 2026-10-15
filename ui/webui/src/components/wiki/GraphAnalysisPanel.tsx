import {
  Network, BarChart3, Crown, Users, Zap, Loader2, AlertCircle,
} from 'lucide-react';
import { GraphAnalysis } from '../../api';
import { EmptyState } from '../ui/states';
import { cn } from '@/lib/utils';

interface GraphAnalysisPanelProps {
  data: GraphAnalysis | null;
  loading: boolean;
  onRun?: () => void;
  runLabel?: string;
  hideRunButton?: boolean;
}

export function GraphAnalysisPanel({
  data,
  loading,
  onRun,
  runLabel = 'Run Analysis',
  hideRunButton = false,
}: GraphAnalysisPanelProps) {
  return (
    <section className="rounded-xl glass p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Network className="w-4 h-4 text-primary" />
            Graph Analysis
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Central topics, community structure, and page suggestions
          </p>
        </div>
        {!hideRunButton && onRun && (
          <button
            onClick={onRun}
            disabled={loading}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium',
              'glass hover:bg-white/[0.04] text-foreground/85',
              'transition-colors shrink-0',
              'disabled:opacity-50',
            )}
          >
            {loading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <BarChart3 className="w-3.5 h-3.5" />
            )}
            <span>{loading ? 'Loading…' : runLabel}</span>
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-4">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Analyzing graph…
        </div>
      ) : !data ? (
        <EmptyState
          variant="compact"
          icon={<AlertCircle className="w-5 h-5" />}
          title="Graph analysis unavailable"
          description="Could not compute graph analysis. The wiki endpoint may be unreachable."
        />
      ) : data.status === 'empty' ? (
        <EmptyState
          variant="compact"
          icon={<Network className="w-5 h-5" />}
          title="Wiki is empty"
          description={data.message || 'Add sources and create pages to enable graph analysis.'}
        />
      ) : (
        <div className="space-y-3">
          {data.stats && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <StatTile label="Nodes" value={data.stats.nodes} />
              <StatTile label="Edges" value={data.stats.edges} />
              <StatTile label="Density" value={(data.stats.density ?? 0).toFixed(3)} />
              <StatTile label="Avg Degree" value={(data.stats.avg_degree ?? 0).toFixed(1)} />
              <StatTile label="Connected" value={data.stats.is_connected ? 'Yes' : 'No'} />
            </div>
          )}

          <div className="space-y-3">
            {data.centrality.pagerank.length > 0 && (
              <div className="rounded-lg glass p-4">
                <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                  <Crown className="w-3.5 h-3.5 text-primary" />
                  Top Pages (PageRank)
                </h3>
                <div className="space-y-1.5">
                  {data.centrality.pagerank.slice(0, 5).map((item, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between text-xs px-2 py-1.5 rounded-md hover:bg-white/[0.04] transition-colors"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-muted-foreground font-mono w-5 text-right tabular-nums">
                          {i + 1}
                        </span>
                        <span className="text-foreground truncate">{item.node}</span>
                      </div>
                      <span className="text-muted-foreground font-mono tabular-nums shrink-0">
                        {(item.score ?? 0).toFixed(4)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.communities.num_communities > 0 && (
              <div className="rounded-lg glass p-4">
                <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                  <Users className="w-3.5 h-3.5 text-primary" />
                  Communities ({data.communities.num_communities})
                </h3>
                <p className="text-[10px] text-muted-foreground mb-3">
                  Modularity: <span className="font-mono tabular-nums">{(data.communities.modularity ?? 0).toFixed(3)}</span>
                </p>
                <div className="space-y-1.5">
                  {Object.entries(data.communities.communities).slice(0, 5).map(([cid, comm]) => (
                    <div key={cid} className="flex items-center justify-between text-xs px-2 py-1.5 rounded-md hover:bg-white/[0.04] transition-colors">
                      <span className="text-foreground truncate">{comm.label}</span>
                      <span className="text-muted-foreground font-mono tabular-nums shrink-0 ml-2">
                        {comm.size} nodes
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {data.suggestions.length > 0 && (
            <div className="rounded-lg glass p-4">
              <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                <Zap className="w-3.5 h-3.5 text-primary" />
                Suggested Pages ({data.suggestions.length})
              </h3>
              <div className="space-y-2">
                {data.suggestions.slice(0, 5).map((sugg, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs p-2 rounded-md hover:bg-white/[0.04] transition-colors">
                    <PriorityBadge priority={sugg.priority} />
                    <div className="flex-1 min-w-0">
                      <p className="text-foreground">{sugg.observation}</p>
                      {sugg.suggestion && (
                        <p className="text-[10px] text-muted-foreground mt-0.5">{sugg.suggestion}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md bg-white/[0.04] border border-border/30 p-2.5 text-center">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">
        {label}
      </div>
      <div className="text-base font-bold text-foreground mt-0.5 tabular-nums">{value}</div>
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const tone: Record<string, string> = {
    high: 'bg-destructive/15 text-destructive border-destructive/30',
    medium: 'bg-warning/15 text-warning border-warning/30',
    low: 'bg-white/[0.04] text-muted-foreground border-border/40',
  };
  return (
    <span className={cn(
      'inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider shrink-0',
      tone[priority] || tone.low,
    )}>
      {priority}
    </span>
  );
}