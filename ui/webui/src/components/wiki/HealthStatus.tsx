import { useEffect, useState } from 'react';
import { FileText, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react';
import { api, WikiStatus, SinkStatus } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { cn } from '@/lib/utils';

interface HealthStatusProps {
  currentWiki?: { id?: string; wiki_id?: string } | undefined;
}

export function HealthStatus({ currentWiki }: HealthStatusProps) {
  const { currentWikiId: storeWikiId, isMultiWikiMode } = useWikiStore();
  const currentWikiId = currentWiki?.id || currentWiki?.wiki_id || storeWikiId;
  const [status, setStatus] = useState<WikiStatus | null>(null);
  const [sinkStatus, setSinkStatus] = useState<SinkStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const [s, sink] = await Promise.all([
          isMultiWikiMode && currentWikiId
            ? api.wiki.scoped.status(currentWikiId)
            : api.wiki.status(),
          isMultiWikiMode && currentWikiId
            ? api.wiki.scoped.sinkStatus(currentWikiId).catch(() => null)
            : api.wiki.sinkStatus().catch(() => null),
        ]);
        if (mounted) {
          setStatus(s);
          setSinkStatus(sink);
        }
      } catch { /* silent */ } finally {
        if (mounted) setLoading(false);
      }
    };
    load();
    return () => { mounted = false; };
  }, [currentWikiId, isMultiWikiMode]);

  if (loading) {
    return (
      <div className="mx-2 mb-2 p-2.5 rounded-lg glass-strong flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="w-3 h-3 animate-spin" />
        <span>Loading status…</span>
      </div>
    );
  }

  const pageCount = status?.page_count ?? 0;
  const sinkEntries = sinkStatus?.total_entries ?? 0;
  const urgentSinks = sinkStatus?.urgent_count ?? 0;
  const sinks = sinkStatus?.total_sinks ?? 0;
  const hasIssues = urgentSinks > 0;

  return (
    <div className="mx-2 mb-2 p-2.5 rounded-lg glass-strong space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em]">
          Health
        </span>
        {hasIssues ? (
          <span className="flex items-center gap-1 text-[10px] text-warning font-medium">
            <AlertCircle className="w-3 h-3" />
            <span>{urgentSinks} urgent</span>
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[10px] text-success font-medium">
            <CheckCircle2 className="w-3 h-3" />
            <span>Healthy</span>
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Metric
          icon={FileText}
          label="Pages"
          value={pageCount}
          tone="primary"
        />
        <Metric
          icon={AlertCircle}
          label="Sinks"
          value={`${sinks}`}
          sub={sinkEntries > 0 ? `${sinkEntries} pending` : '0 pending'}
          tone={hasIssues ? 'warning' : 'muted'}
        />
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'muted',
}: {
  icon: typeof FileText;
  label: string;
  value: number | string;
  sub?: string;
  tone?: 'primary' | 'warning' | 'muted';
}) {
  const toneColor: Record<typeof tone, string> = {
    primary: 'text-primary',
    warning: 'text-warning',
    muted: 'text-muted-foreground',
  };

  return (
    <div className="p-1.5 rounded-md bg-white/[0.03] border border-border/30">
      <div className="flex items-center gap-1.5">
        <Icon className={cn('w-3 h-3 shrink-0', toneColor[tone])} />
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
      </div>
      <div className="mt-0.5 flex items-baseline gap-1.5">
        <span className="text-base font-semibold text-foreground tabular-nums">{value}</span>
        {sub && <span className="text-[10px] text-muted-foreground truncate">{sub}</span>}
      </div>
    </div>
  );
}
