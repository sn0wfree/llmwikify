import { useState, useEffect, useMemo } from 'react';
import {
  FileText, Database, Activity, AlertTriangle, Sparkles, PlayCircle,
  RefreshCw, Circle, BarChart3, Clock,
} from 'lucide-react';
import { api, WikiStatus, SinkStatus, WikiDreamEdit } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { LoadingState, EmptyState } from '../ui/states';
import { cn } from '@/lib/utils';

interface GrowthMetrics {
  pages: number;
  sinkEntries: number;
  sinkCount: number;
  urgentSinks: number;
  wikiDreamEdits: number;
  wikiDreamRuns: number;
}

interface ActivityEntry {
  timestamp: string;
  type: 'wiki_dream' | 'warning' | 'info';
  description: string;
}

interface KnowledgeGrowthProps {
  currentWikiId?: string | null;
  isMultiWikiMode?: boolean;
}

export function KnowledgeGrowth({ currentWikiId: propWikiId, isMultiWikiMode: propMultiWiki }: KnowledgeGrowthProps) {
  const { currentWikiId: storeWikiId, isMultiWikiMode: storeMultiWiki } = useWikiStore();
  const currentWikiId = propWikiId ?? storeWikiId;
  const isMultiWikiMode = propMultiWiki ?? storeMultiWiki;
  const [wikiStatus, setWikiStatus] = useState<WikiStatus | null>(null);
  const [sinkStatus, setSinkStatus] = useState<SinkStatus | null>(null);
  const [wikiDreamLog, setWikiDreamLog] = useState<WikiDreamEdit[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => { loadData(); }, [currentWikiId, isMultiWikiMode]);

  const loadData = async () => {
    try {
      const [status, sink, wikiDream] = await Promise.all([
        isMultiWikiMode && currentWikiId ? api.wiki.scoped.status(currentWikiId).catch(() => null) : api.wiki.status().catch(() => null),
        isMultiWikiMode && currentWikiId ? api.wiki.scoped.sinkStatus(currentWikiId).catch(() => null) : api.wiki.sinkStatus().catch(() => null),
        api.wikiDream.log(50).catch(() => []),
      ]);
      setWikiStatus(status);
      setSinkStatus(sink);
      setWikiDreamLog(wikiDream);
    } catch { /* Ignore */ } finally { setLoading(false); }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  const metrics = useMemo<GrowthMetrics>(() => ({
    pages: wikiStatus?.page_count ?? 0,
    sinkEntries: sinkStatus?.total_entries ?? 0,
    sinkCount: sinkStatus?.total_sinks ?? 0,
    urgentSinks: sinkStatus?.urgent_count ?? 0,
    wikiDreamEdits: wikiDreamLog.reduce((sum, d) => sum + d.edits_applied, 0),
    wikiDreamRuns: wikiDreamLog.length,
  }), [wikiStatus, sinkStatus, wikiDreamLog]);

  const activities = useMemo<ActivityEntry[]>(() => {
    const entries: ActivityEntry[] = [];
    wikiDreamLog.forEach((d) => {
      entries.push({ timestamp: d.timestamp, type: 'wiki_dream', description: `Wiki Dream: ${d.edits_applied} edits across ${d.sinks_processed} sinks` });
    });
    sinkStatus?.sinks?.forEach((s) => {
      if (s.urgency !== 'ok') {
        entries.push({ timestamp: new Date().toISOString(), type: 'warning', description: `Sink "${s.page_name}" has ${s.entry_count} pending entries (${s.urgency})` });
      }
    });
    entries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    return entries.slice(0, 20);
  }, [wikiDreamLog, sinkStatus]);

  const sinkDistribution = useMemo(() => {
    if (!sinkStatus?.sinks) return [];
    return sinkStatus.sinks.filter((s) => s.entry_count > 0).sort((a, b) => b.entry_count - a.entry_count).slice(0, 8);
  }, [sinkStatus]);

  const maxSinkEntries = useMemo(() => Math.max(...sinkDistribution.map((s) => s.entry_count), 1), [sinkDistribution]);

  if (loading) return <LoadingState message="Loading dashboard…" />;

  return (
    <div className="overflow-y-auto h-full">
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-end justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-foreground tracking-tight">Dashboard</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Knowledge growth and sink health overview
            </p>
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium',
              'glass hover:bg-white/[0.04] text-foreground/85',
              'transition-colors',
            )}
          >
            <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            <span>Refresh</span>
          </button>
        </div>

        {/* KPI Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-8">
          <KPICard label="Pages" value={metrics.pages} icon={FileText} tone="primary" />
          <KPICard label="Sink Entries" value={metrics.sinkEntries} icon={Database} tone="warning" />
          <KPICard label="Active Sinks" value={metrics.sinkCount} icon={Activity} tone="info" />
          <KPICard label="Urgent" value={metrics.urgentSinks} icon={AlertTriangle} tone={metrics.urgentSinks > 0 ? 'danger' : 'muted'} />
          <KPICard label="Wiki Dream Edits" value={metrics.wikiDreamEdits} icon={Sparkles} tone="success" />
          <KPICard label="Wiki Dream Runs" value={metrics.wikiDreamRuns} icon={PlayCircle} tone="info" />
        </div>

        {/* Charts Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
          {/* Sink Distribution */}
          <div className="rounded-xl glass p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-primary" />
                Sink Entry Distribution
              </h2>
              <span className="text-[10px] text-muted-foreground font-mono">
                top {sinkDistribution.length}
              </span>
            </div>
            {sinkDistribution.length === 0 ? (
              <EmptyState
                variant="compact"
                icon={<Database className="w-5 h-5" />}
                title="No sink data"
                description="Sinks will appear here once they collect entries."
              />
            ) : (
              <div className="space-y-2.5">
                {sinkDistribution.map((s) => {
                  const pct = (s.entry_count / maxSinkEntries) * 100;
                  const urgencyColor: Record<string, string> = {
                    ok: 'bg-success',
                    attention: 'bg-warning',
                    aging: 'bg-orange-500',
                    stale: 'bg-destructive',
                  };
                  const barColor = urgencyColor[s.urgency] || 'bg-success';
                  return (
                    <div key={s.page_name} className="flex items-center gap-2.5">
                      <span
                        className="w-32 text-xs text-muted-foreground truncate shrink-0"
                        title={s.page_name}
                      >
                        {s.page_name}
                      </span>
                      <div className="flex-1 h-2 rounded-full bg-white/[0.04] border border-border/30 overflow-hidden">
                        <div
                          className={cn('h-full rounded-full transition-all duration-700 ease-out', barColor)}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-8 text-xs text-foreground text-right tabular-nums font-mono">
                        {s.entry_count}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Knowledge Health Donut */}
          <div className="rounded-xl glass p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Activity className="w-4 h-4 text-primary" />
                Knowledge Health
              </h2>
            </div>
            <HealthDonut
              pages={metrics.pages}
              sinkEntries={metrics.sinkEntries}
              wikiDreamEdits={metrics.wikiDreamEdits}
              urgentSinks={metrics.urgentSinks}
            />
          </div>

          {/* Wiki Dream Activity */}
          <div className="rounded-xl glass p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary" />
                Wiki Dream Activity
              </h2>
              <span className="text-[10px] text-muted-foreground font-mono">
                {wikiDreamLog.length} runs
              </span>
            </div>
            {wikiDreamLog.length === 0 ? (
              <EmptyState
                variant="compact"
                icon={<Sparkles className="w-5 h-5" />}
                title="No wiki dream runs"
                description="Run a wiki dream pass to consolidate sinks."
              />
            ) : (
              <div className="space-y-3 max-h-72 overflow-y-auto pr-2 -mr-2">
                {wikiDreamLog.slice(0, 10).map((d, i) => (
                  <div key={i} className="flex items-start gap-3 group">
                    <div className="relative shrink-0 mt-1.5">
                      <div className="w-2 h-2 rounded-full bg-primary ring-2 ring-background" />
                      <div className="absolute top-2 left-1/2 -translate-x-1/2 w-px h-full bg-border/40 group-last:hidden" />
                    </div>
                    <div className="flex-1 min-w-0 -mt-0.5">
                      <p className="text-xs text-foreground">
                        <span className="font-medium">{d.edits_applied}</span> edits,
                        {' '}<span className="text-muted-foreground">{d.sinks_processed}</span> sinks
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">{formatTime(d.timestamp)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recent Activity */}
          <div className="rounded-xl glass p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Clock className="w-4 h-4 text-primary" />
                Recent Activity
              </h2>
              <span className="text-[10px] text-muted-foreground font-mono">
                {activities.length}
              </span>
            </div>
            {activities.length === 0 ? (
              <EmptyState
                variant="compact"
                icon={<Clock className="w-5 h-5" />}
                title="No activity"
                description="Activity will appear here as the wiki grows."
              />
            ) : (
              <div className="space-y-3 max-h-72 overflow-y-auto pr-2 -mr-2">
                {activities.slice(0, 15).map((a, i) => (
                  <div key={i} className="flex items-start gap-3 group">
                    <div className="relative shrink-0 mt-1.5">
                      <div className={cn(
                        'w-2 h-2 rounded-full ring-2 ring-background',
                        a.type === 'wiki_dream' && 'bg-success',
                        a.type === 'warning' && 'bg-warning',
                        a.type === 'info' && 'bg-primary',
                      )} />
                      <div className="absolute top-2 left-1/2 -translate-x-1/2 w-px h-full bg-border/40 group-last:hidden" />
                    </div>
                    <div className="flex-1 min-w-0 -mt-0.5">
                      <p className="text-xs text-foreground/90 truncate">{a.description}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">{formatTime(a.timestamp)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Urgency Legend */}
        {sinkStatus && sinkStatus.total_entries > 0 && (
          <div className="rounded-xl glass p-5">
            <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <Circle className="w-4 h-4 text-primary" />
              Sink Urgency Legend
            </h2>
            <div className="flex flex-wrap gap-3 text-xs">
              <UrgencyBadge tone="ok" label="OK" range="≤7 days" />
              <UrgencyBadge tone="attention" label="Attention" range="7-14 days" />
              <UrgencyBadge tone="aging" label="Aging" range="14-30 days" />
              <UrgencyBadge tone="stale" label="Stale" range=">30 days" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function KPICard({
  label, value, icon: Icon, tone,
}: {
  label: string;
  value: number;
  icon: typeof FileText;
  tone: 'primary' | 'warning' | 'info' | 'danger' | 'success' | 'muted';
}) {
  const toneClass: Record<typeof tone, string> = {
    primary: 'text-primary bg-primary/10',
    warning: 'text-warning bg-warning/10',
    info: 'text-foreground/80 bg-foreground/5',
    danger: 'text-destructive bg-destructive/10',
    success: 'text-success bg-success/10',
    muted: 'text-muted-foreground bg-white/[0.04]',
  };
  return (
    <div className="rounded-xl glass p-4 hover:bg-white/[0.04] transition-colors group">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.1em]">
          {label}
        </span>
        <div className={cn('w-6 h-6 rounded-md flex items-center justify-center', toneClass[tone])}>
          <Icon className="w-3.5 h-3.5" />
        </div>
      </div>
      <div className="text-2xl font-bold text-foreground tabular-nums tracking-tight">
        {value}
      </div>
    </div>
  );
}

function UrgencyBadge({ tone, label, range }: { tone: string; label: string; range: string }) {
  const toneStyle: Record<string, string> = {
    ok: 'bg-success/15 text-success border-success/30',
    attention: 'bg-warning/15 text-warning border-warning/30',
    aging: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
    stale: 'bg-destructive/15 text-destructive border-destructive/30',
  };
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] font-medium',
      toneStyle[tone],
    )}>
      <span className="font-semibold">{label}</span>
      <span className="opacity-70">({range})</span>
    </span>
  );
}

function HealthDonut({ pages, sinkEntries, wikiDreamEdits, urgentSinks }: { pages: number; sinkEntries: number; wikiDreamEdits: number; urgentSinks: number }) {
  const total = pages + sinkEntries + wikiDreamEdits + Math.max(urgentSinks, 0);
  if (total === 0) {
    return (
      <EmptyState
        variant="compact"
        icon={<Activity className="w-5 h-5" />}
        title="No data"
        description="The wiki is empty."
      />
    );
  }

  const size = 180;
  const strokeWidth = 22;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const segments = [
    { label: 'Pages', value: pages, colorVar: '--chart-1' },
    { label: 'Sink Entries', value: sinkEntries, colorVar: '--chart-2' },
    { label: 'Wiki Dream Edits', value: wikiDreamEdits, colorVar: '--chart-3' },
    { label: 'Urgent', value: urgentSinks, colorVar: '--destructive' },
  ].filter((s) => s.value > 0);

  let cumulativeOffset = 0;

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="overflow-visible">
        {/* Track ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeOpacity="0.3"
          strokeWidth={strokeWidth}
        />
        {segments.map((seg, i) => {
          const pct = seg.value / total;
          const dashLength = pct * circumference;
          const dashOffset = -cumulativeOffset;
          cumulativeOffset += dashLength;
          return (
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={`var(${seg.colorVar})`}
              strokeWidth={strokeWidth}
              strokeDasharray={`${dashLength} ${circumference - dashLength}`}
              strokeDashoffset={dashOffset}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              className="transition-all duration-500"
            />
          );
        })}
        <text
          x={size / 2}
          y={size / 2 - 6}
          textAnchor="middle"
          className="fill-foreground"
          style={{ fontSize: '28px', fontWeight: 700 }}
        >
          {total}
        </text>
        <text
          x={size / 2}
          y={size / 2 + 14}
          textAnchor="middle"
          className="fill-muted-foreground"
          style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em' }}
        >
          total items
        </text>
      </svg>
      <div className="flex flex-wrap gap-x-3 gap-y-1.5 mt-4 justify-center">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-1.5 text-xs">
            <span
              className="w-2.5 h-2.5 rounded-full ring-1 ring-border/30"
              style={{ background: `var(${seg.colorVar})` }}
            />
            <span className="text-muted-foreground">{seg.label}</span>
            <span className="text-foreground font-semibold tabular-nums">{seg.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return d.toLocaleDateString();
  } catch { return iso; }
}
