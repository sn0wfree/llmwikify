import { WikiStatus, SinkStatus } from '../api';

interface HealthStatusProps {
  status: WikiStatus | null;
  sinkStatus: SinkStatus | null;
}

export function HealthStatus({ status, sinkStatus }: HealthStatusProps) {
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
