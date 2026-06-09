import { useState, useEffect, useMemo } from 'react';
import { api, WikiStatus, SinkStatus, DreamEdit } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { Card } from '../ui/card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/badge';
import { cn } from '@/lib/utils';

interface GrowthMetrics {
  pages: number;
  sinkEntries: number;
  sinkCount: number;
  urgentSinks: number;
  dreamEdits: number;
  dreamRuns: number;
}

interface ActivityEntry {
  timestamp: string;
  type: string;
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
  const [dreamLog, setDreamLog] = useState<DreamEdit[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadData(); }, [currentWikiId, isMultiWikiMode]);

  const loadData = async () => {
    try {
      const [status, sink, dream] = await Promise.all([
        isMultiWikiMode && currentWikiId ? api.wiki.scoped.status(currentWikiId).catch(() => null) : api.wiki.status().catch(() => null),
        isMultiWikiMode && currentWikiId ? api.wiki.scoped.sinkStatus(currentWikiId).catch(() => null) : api.wiki.sinkStatus().catch(() => null),
        api.dream.log(50).catch(() => []),
      ]);
      setWikiStatus(status);
      setSinkStatus(sink);
      setDreamLog(dream);
    } catch { /* Ignore */ } finally { setLoading(false); }
  };

  const metrics = useMemo<GrowthMetrics>(() => ({
    pages: wikiStatus?.page_count ?? 0,
    sinkEntries: sinkStatus?.total_entries ?? 0,
    sinkCount: sinkStatus?.total_sinks ?? 0,
    urgentSinks: sinkStatus?.urgent_count ?? 0,
    dreamEdits: dreamLog.reduce((sum, d) => sum + d.edits_applied, 0),
    dreamRuns: dreamLog.length,
  }), [wikiStatus, sinkStatus, dreamLog]);

  const activities = useMemo<ActivityEntry[]>(() => {
    const entries: ActivityEntry[] = [];
    dreamLog.forEach((d) => {
      entries.push({ timestamp: d.timestamp, type: 'dream', description: `Dream: ${d.edits_applied} edits across ${d.sinks_processed} sinks` });
    });
    sinkStatus?.sinks?.forEach((s) => {
      if (s.urgency !== 'ok') {
        entries.push({ timestamp: new Date().toISOString(), type: 'warning', description: `Sink "${s.page_name}" has ${s.entry_count} pending entries (${s.urgency})` });
      }
    });
    entries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    return entries.slice(0, 20);
  }, [dreamLog, sinkStatus]);

  const sinkDistribution = useMemo(() => {
    if (!sinkStatus?.sinks) return [];
    return sinkStatus.sinks.filter((s) => s.entry_count > 0).sort((a, b) => b.entry_count - a.entry_count).slice(0, 10);
  }, [sinkStatus]);

  const maxSinkEntries = useMemo(() => Math.max(...sinkDistribution.map((s) => s.entry_count), 1), [sinkDistribution]);

  if (loading) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">Loading knowledge growth...</div>;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">Dashboard</h2>
        <Button variant="ghost" size="sm" onClick={loadData}>Refresh</Button>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
        <MetricCard label="Pages" value={metrics.pages} color="teal" />
        <MetricCard label="Sink Entries" value={metrics.sinkEntries} color="amber" />
        <MetricCard label="Active Sinks" value={metrics.sinkCount} color="blue" />
        <MetricCard label="Urgent" value={metrics.urgentSinks} color="red" />
        <MetricCard label="Dream Edits" value={metrics.dreamEdits} color="green" />
        <MetricCard label="Dream Runs" value={metrics.dreamRuns} color="cyan" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sink Distribution Chart */}
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-foreground mb-4">Sink Entry Distribution</h3>
          {sinkDistribution.length === 0 ? (
            <p className="text-muted-foreground text-sm text-center py-8">No sink data</p>
          ) : (
            <div className="space-y-2">
              {sinkDistribution.map((s) => {
                const pct = (s.entry_count / maxSinkEntries) * 100;
                const urgencyColor = { ok: 'bg-green-500', attention: 'bg-yellow-500', aging: 'bg-orange-500', stale: 'bg-red-500' }[s.urgency] || 'bg-green-500';
                return (
                  <div key={s.page_name} className="flex items-center gap-2">
                    <span className="w-32 text-xs text-muted-foreground truncate" title={s.page_name}>{s.page_name}</span>
                    <div className="flex-1 bg-muted rounded-full h-4 overflow-hidden">
                      <div className={cn('h-full rounded-full transition-all duration-500', urgencyColor)} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-8 text-xs text-foreground text-right">{s.entry_count}</span>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* Knowledge Health Donut */}
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-foreground mb-4">Knowledge Health</h3>
          <div className="flex items-center justify-center">
            <HealthDonut pages={metrics.pages} sinkEntries={metrics.sinkEntries} dreamEdits={metrics.dreamEdits} urgentSinks={metrics.urgentSinks} />
          </div>
        </Card>

        {/* Dream Activity Timeline */}
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-foreground mb-4">Dream Activity</h3>
          {dreamLog.length === 0 ? (
            <p className="text-muted-foreground text-sm text-center py-8">No dream runs recorded</p>
          ) : (
            <div className="space-y-3 max-h-64 overflow-y-auto">
              {dreamLog.slice(0, 10).map((d, i) => (
                <div key={i} className="flex items-start gap-3">
                  <div className="w-2 h-2 rounded-full bg-primary mt-1.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-foreground">{d.edits_applied} edits, {d.sinks_processed} sinks</p>
                    <p className="text-xs text-muted-foreground">{formatTime(d.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Recent Activity Feed */}
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-foreground mb-4">Recent Activity</h3>
          {activities.length === 0 ? (
            <p className="text-muted-foreground text-sm text-center py-8">No recent activity</p>
          ) : (
            <div className="space-y-3 max-h-64 overflow-y-auto">
              {activities.slice(0, 15).map((a, i) => (
                <div key={i} className="flex items-start gap-3">
                  <ActivityDot type={a.type} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-foreground truncate">{a.description}</p>
                    <p className="text-xs text-muted-foreground">{formatTime(a.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Sink Urgency Legend */}
      {sinkStatus && sinkStatus.total_entries > 0 && (
        <Card className="mt-6 p-4">
          <h3 className="text-sm font-semibold text-foreground mb-3">Sink Urgency Legend</h3>
          <div className="flex flex-wrap gap-4 text-xs">
            <Badge variant="secondary">OK (≤7 days)</Badge>
            <Badge variant="outline" className="border-yellow-500/50 text-yellow-500">Attention (7-14 days)</Badge>
            <Badge variant="outline" className="border-orange-500/50 text-orange-500">Aging (14-30 days)</Badge>
            <Badge variant="destructive">Stale (&gt;30 days)</Badge>
          </div>
        </Card>
      )}
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: number; color: string }) {
  const colorMap: Record<string, string> = {
    teal: 'border-l-primary', amber: 'border-l-yellow-500', blue: 'border-l-blue-500',
    red: 'border-l-destructive', green: 'border-l-green-500', cyan: 'border-l-cyan-500',
  };
  const textColorMap: Record<string, string> = {
    teal: 'text-primary', amber: 'text-yellow-500', blue: 'text-blue-500',
    red: 'text-destructive', green: 'text-green-500', cyan: 'text-cyan-500',
  };

  return (
    <Card className={cn('p-4 border-l-2', colorMap[color])}>
      <div className="text-xs text-muted-foreground mb-1.5">{label}</div>
      <div className={cn('text-2xl font-bold', textColorMap[color])}>{value}</div>
    </Card>
  );
}

function HealthDonut({ pages, sinkEntries, dreamEdits, urgentSinks }: { pages: number; sinkEntries: number; dreamEdits: number; urgentSinks: number }) {
  const total = pages + sinkEntries + dreamEdits + Math.max(urgentSinks, 0);
  if (total === 0) return <p className="text-muted-foreground text-sm">No data</p>;

  const size = 160;
  const strokeWidth = 20;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const segments = [
    { label: 'Pages', value: pages, color: 'var(--primary)' },
    { label: 'Sink Entries', value: sinkEntries, color: 'var(--chart-2)' },
    { label: 'Dream Edits', value: dreamEdits, color: 'var(--chart-3)' },
    { label: 'Urgent', value: urgentSinks, color: 'var(--destructive)' },
  ].filter((s) => s.value > 0);

  let cumulativeOffset = 0;

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {segments.map((seg, i) => {
          const pct = seg.value / total;
          const dashLength = pct * circumference;
          const dashOffset = -cumulativeOffset;
          cumulativeOffset += dashLength;
          return (
            <circle key={i} cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={seg.color}
              strokeWidth={strokeWidth} strokeDasharray={`${dashLength} ${circumference - dashLength}`}
              strokeDashoffset={dashOffset} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
          );
        })}
        <text x={size / 2} y={size / 2 - 8} textAnchor="middle" className="fill-foreground text-2xl font-bold">{total}</text>
        <text x={size / 2} y={size / 2 + 12} textAnchor="middle" className="fill-muted-foreground text-xs">total items</text>
      </svg>
      <div className="flex flex-wrap gap-3 mt-3 justify-center">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-1.5 text-xs">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: seg.color }} />
            <span className="text-muted-foreground">{seg.label}</span>
            <span className="text-foreground font-medium">{seg.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityDot({ type }: { type: string }) {
  const colors: Record<string, string> = { dream: 'bg-green-500', warning: 'bg-yellow-500', info: 'bg-primary', error: 'bg-destructive' };
  return <div className={cn('w-2 h-2 rounded-full mt-1.5 shrink-0', colors[type] || colors.info)} />;
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
