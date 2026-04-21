import { api, WikiStatus, SinkStatus } from '../api';

interface HealthStatusProps {
  status: WikiStatus | null;
  sinkStatus: SinkStatus | null;
  full?: boolean;
}

export function HealthStatus({ status, sinkStatus, full }: HealthStatusProps) {
  if (full) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <h2 className="text-xl font-bold mb-4">Wiki Health</h2>
        <div className="grid grid-cols-2 gap-4">
          <StatCard label="Pages" value={status?.page_count ?? 0} />
          <StatCard label="Sink Entries" value={sinkStatus?.total_entries ?? 0} />
          <StatCard label="Active Sinks" value={sinkStatus?.total_sinks ?? 0} />
          <StatCard
            label="Urgent"
            value={sinkStatus?.urgent_count ?? 0}
            color={sinkStatus?.urgent_count ? 'text-red-400' : 'text-green-400'}
          />
        </div>
        <div className="mt-6">
          <h3 className="text-lg font-semibold mb-2">Sink Details</h3>
          {sinkStatus?.sinks?.map((s) => (
            <div
              key={s.page_name}
              className="flex items-center justify-between p-3 bg-slate-800 rounded mb-2"
            >
              <span className="text-sm">{s.page_name}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">{s.entry_count} entries</span>
                <UrgencyBadge urgency={s.urgency} />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="px-2 py-1">
      <div className="flex items-center gap-2 text-xs">
        <span className="text-slate-400">Pages:</span>
        <span className="text-slate-200">{status?.page_count ?? '-'}</span>
      </div>
      {sinkStatus && sinkStatus.total_entries > 0 && (
        <div className="flex items-center gap-2 text-xs mt-1">
          <span className="text-slate-400">Sink:</span>
          <span
            className={
              sinkStatus.urgent_count > 0 ? 'text-amber-400' : 'text-green-400'
            }
          >
            {sinkStatus.total_entries} pending
          </span>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  color = 'text-slate-200',
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div className="bg-slate-800 rounded p-4 border border-slate-700">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

function UrgencyBadge({ urgency }: { urgency: string }) {
  const colors: Record<string, string> = {
    ok: 'bg-green-500/20 text-green-400',
    attention: 'bg-yellow-500/20 text-yellow-400',
    aging: 'bg-orange-500/20 text-orange-400',
    stale: 'bg-red-500/20 text-red-400',
  };
  return (
    <span className={`px-1.5 py-0.5 text-xs rounded ${colors[urgency] || colors.ok}`}>
      {urgency}
    </span>
  );
}
