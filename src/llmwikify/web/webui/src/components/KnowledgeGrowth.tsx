import { useState, useEffect, useMemo } from 'react';
import { api, WikiStatus, SinkStatus, DreamEdit } from '../api';

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

export function KnowledgeGrowth() {
  const [wikiStatus, setWikiStatus] = useState<WikiStatus | null>(null);
  const [sinkStatus, setSinkStatus] = useState<SinkStatus | null>(null);
  const [dreamLog, setDreamLog] = useState<DreamEdit[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [status, sink, dream] = await Promise.all([
        api.wiki.status().catch(() => null),
        api.wiki.sinkStatus().catch(() => null),
        api.dream.log(50).catch(() => []),
      ]);
      setWikiStatus(status);
      setSinkStatus(sink);
      setDreamLog(dream);
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
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

    // Dream activities
    dreamLog.forEach((d) => {
      entries.push({
        timestamp: d.timestamp,
        type: 'dream',
        description: `Dream: ${d.edits_applied} edits across ${d.sinks_processed} sinks`,
      });
    });

    // Sink urgency
    sinkStatus?.sinks?.forEach((s) => {
      if (s.urgency !== 'ok') {
        entries.push({
          timestamp: new Date().toISOString(),
          type: 'warning',
          description: `Sink "${s.page_name}" has ${s.entry_count} pending entries (${s.urgency})`,
        });
      }
    });

    entries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    return entries.slice(0, 20);
  }, [dreamLog, sinkStatus]);

  const sinkDistribution = useMemo(() => {
    if (!sinkStatus?.sinks) return [];
    return sinkStatus.sinks
      .filter((s) => s.entry_count > 0)
      .sort((a, b) => b.entry_count - a.entry_count)
      .slice(0, 10);
  }, [sinkStatus]);

  const maxSinkEntries = useMemo(() => {
    return Math.max(...sinkDistribution.map((s) => s.entry_count), 1);
  }, [sinkDistribution]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Loading knowledge growth...
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">Knowledge Growth</h2>
        <button
          onClick={loadData}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 rounded"
        >
          Refresh
        </button>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
        <MetricCard label="Pages" value={metrics.pages} icon="📄" color="blue" />
        <MetricCard label="Sink Entries" value={metrics.sinkEntries} icon="📥" color="amber" />
        <MetricCard label="Active Sinks" value={metrics.sinkCount} icon="📋" color="purple" />
        <MetricCard label="Urgent" value={metrics.urgentSinks} icon="⚠️" color="red" />
        <MetricCard label="Dream Edits" value={metrics.dreamEdits} icon="✨" color="green" />
        <MetricCard label="Dream Runs" value={metrics.dreamRuns} icon="🔄" color="cyan" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sink Distribution Chart */}
        <section className="bg-slate-800 rounded-lg border border-slate-700 p-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Sink Entry Distribution</h3>
          {sinkDistribution.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">No sink data</p>
          ) : (
            <div className="space-y-2">
              {sinkDistribution.map((s) => {
                const pct = (s.entry_count / maxSinkEntries) * 100;
                const urgencyColor = {
                  ok: 'bg-green-500',
                  attention: 'bg-yellow-500',
                  aging: 'bg-orange-500',
                  stale: 'bg-red-500',
                }[s.urgency] || 'bg-green-500';

                return (
                  <div key={s.page_name} className="flex items-center gap-2">
                    <span className="w-32 text-xs text-slate-400 truncate" title={s.page_name}>
                      {s.page_name}
                    </span>
                    <div className="flex-1 bg-slate-700 rounded-full h-4 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${urgencyColor} transition-all duration-500`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="w-8 text-xs text-slate-300 text-right">{s.entry_count}</span>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Knowledge Health Donut */}
        <section className="bg-slate-800 rounded-lg border border-slate-700 p-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Knowledge Health</h3>
          <div className="flex items-center justify-center">
            <HealthDonut
              pages={metrics.pages}
              sinkEntries={metrics.sinkEntries}
              dreamEdits={metrics.dreamEdits}
              urgentSinks={metrics.urgentSinks}
            />
          </div>
        </section>

        {/* Dream Activity Timeline */}
        <section className="bg-slate-800 rounded-lg border border-slate-700 p-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Dream Activity</h3>
          {dreamLog.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">No dream runs recorded</p>
          ) : (
            <div className="space-y-3 max-h-64 overflow-y-auto">
              {dreamLog.slice(0, 10).map((d, i) => (
                <div key={i} className="flex items-start gap-3">
                  <div className="w-2 h-2 rounded-full bg-green-400 mt-1.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-300">
                      {d.edits_applied} edits, {d.sinks_processed} sinks
                    </p>
                    <p className="text-xs text-slate-500">{formatTime(d.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Recent Activity Feed */}
        <section className="bg-slate-800 rounded-lg border border-slate-700 p-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Recent Activity</h3>
          {activities.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">No recent activity</p>
          ) : (
            <div className="space-y-3 max-h-64 overflow-y-auto">
              {activities.slice(0, 15).map((a, i) => (
                <div key={i} className="flex items-start gap-3">
                  <ActivityDot type={a.type} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-300 truncate">{a.description}</p>
                    <p className="text-xs text-slate-500">{formatTime(a.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Sink Urgency Legend */}
      {sinkStatus && sinkStatus.total_entries > 0 && (
        <section className="mt-6 bg-slate-800 rounded-lg border border-slate-700 p-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-3">Sink Urgency Legend</h3>
          <div className="flex flex-wrap gap-4 text-xs">
            <UrgencyBadge urgency="ok" label="OK (≤7 days)" />
            <UrgencyBadge urgency="attention" label="Attention (7-14 days)" />
            <UrgencyBadge urgency="aging" label="Aging (14-30 days)" />
            <UrgencyBadge urgency="stale" label="Stale (>30 days)" />
          </div>
        </section>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: number;
  icon: string;
  color: string;
}) {
  const borderColors: Record<string, string> = {
    blue: 'border-blue-500/30',
    amber: 'border-amber-500/30',
    purple: 'border-purple-500/30',
    red: 'border-red-500/30',
    green: 'border-green-500/30',
    cyan: 'border-cyan-500/30',
  };
  const textColors: Record<string, string> = {
    blue: 'text-blue-400',
    amber: 'text-amber-400',
    purple: 'text-purple-400',
    red: 'text-red-400',
    green: 'text-green-400',
    cyan: 'text-cyan-400',
  };

  return (
    <div className={`bg-slate-800 rounded-lg border ${borderColors[color]} p-3`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm">{icon}</span>
        <span className="text-xs text-slate-400">{label}</span>
      </div>
      <div className={`text-2xl font-bold ${textColors[color]}`}>{value}</div>
    </div>
  );
}

function HealthDonut({
  pages,
  sinkEntries,
  dreamEdits,
  urgentSinks,
}: {
  pages: number;
  sinkEntries: number;
  dreamEdits: number;
  urgentSinks: number;
}) {
  const total = pages + sinkEntries + dreamEdits + Math.max(urgentSinks, 0);
  if (total === 0) {
    return <p className="text-slate-500 text-sm">No data</p>;
  }

  const size = 160;
  const strokeWidth = 20;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const segments = [
    { label: 'Pages', value: pages, color: '#3b82f6' },
    { label: 'Sink Entries', value: sinkEntries, color: '#f59e0b' },
    { label: 'Dream Edits', value: dreamEdits, color: '#22c55e' },
    { label: 'Urgent', value: urgentSinks, color: '#ef4444' },
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
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={seg.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${dashLength} ${circumference - dashLength}`}
              strokeDashoffset={dashOffset}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            />
          );
        })}
        <text
          x={size / 2}
          y={size / 2 - 8}
          textAnchor="middle"
          className="fill-slate-200 text-2xl font-bold"
        >
          {total}
        </text>
        <text
          x={size / 2}
          y={size / 2 + 12}
          textAnchor="middle"
          className="fill-slate-500 text-xs"
        >
          total items
        </text>
      </svg>
      <div className="flex flex-wrap gap-3 mt-3 justify-center">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-1.5 text-xs">
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: seg.color }}
            />
            <span className="text-slate-400">{seg.label}</span>
            <span className="text-slate-200 font-medium">{seg.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityDot({ type }: { type: string }) {
  const colors: Record<string, string> = {
    dream: 'bg-green-400',
    warning: 'bg-amber-400',
    info: 'bg-blue-400',
    error: 'bg-red-400',
  };
  return <div className={`w-2 h-2 rounded-full ${colors[type] || colors.info} mt-1.5 shrink-0`} />;
}

function UrgencyBadge({ urgency, label }: { urgency: string; label: string }) {
  const colors: Record<string, string> = {
    ok: 'bg-green-500/20 text-green-400',
    attention: 'bg-yellow-500/20 text-yellow-400',
    aging: 'bg-orange-500/20 text-orange-400',
    stale: 'bg-red-500/20 text-red-400',
  };
  return (
    <span className={`px-2 py-1 rounded ${colors[urgency] || colors.ok}`}>
      {label}
    </span>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return d.toLocaleDateString();
  } catch {
    return iso;
  }
}
