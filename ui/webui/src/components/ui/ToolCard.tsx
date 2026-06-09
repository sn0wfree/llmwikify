import { useState, useEffect } from 'react';
import {
  Search, FileText, Pencil, FileEdit, FilePlus, Trash2,
  Brain, Link2, AlertTriangle, Wrench, Loader2,
  CheckCircle2, XCircle, ChevronDown, ChevronRight, Hash,
} from 'lucide-react';
import { Badge } from './badge';

type ToolStatus = 'pending' | 'streaming' | 'done' | 'error';

interface ToolCardProps {
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  result?: unknown;
  error?: string;
  startedAt?: number;
  finishedAt?: number;
}

const TOOL_ICONS: Record<string, typeof Wrench> = {
  wiki_search: Search, wiki_read_page: FileText, wiki_write_page: Pencil,
  wiki_edit_page: FileEdit, wiki_create_page: FilePlus, wiki_delete_page: Trash2,
  wiki_analyze_source: Brain, wiki_suggest_synthesis: Link2,
  confirmation_required: AlertTriangle,
};

const STATUS_ICON: Record<ToolStatus, typeof Loader2> = {
  pending: Loader2, streaming: Loader2, done: CheckCircle2, error: XCircle,
};

const statusColorMap: Record<ToolStatus, string> = {
  pending: 'border-yellow-500/50',
  streaming: 'border-primary/50',
  done: 'border-green-500/50',
  error: 'border-destructive/50',
};

const statusBadgeVariant: Record<ToolStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  pending: 'outline', streaming: 'outline', done: 'secondary', error: 'destructive',
};

const statusText: Record<ToolStatus, string> = {
  pending: 'pending', streaming: 'running', done: 'done', error: 'error',
};

function truncateJson(obj: unknown, maxLen = 200): string {
  const str = JSON.stringify(obj, null, 2);
  return str.length <= maxLen ? str : str.slice(0, maxLen) + '…';
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${((ms % 60000) / 1000).toFixed(0)}s`;
}

function useElapsedMs(startedAt?: number, finishedAt?: number): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!startedAt || finishedAt) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [startedAt, finishedAt]);
  return startedAt ? (finishedAt ?? now) - startedAt : 0;
}

export function ToolCard({ tool, args, status, result, error, startedAt, finishedAt }: ToolCardProps) {
  const [argsExpanded, setArgsExpanded] = useState(false);
  const [resultExpanded, setResultExpanded] = useState(false);
  const elapsed = useElapsedMs(startedAt, finishedAt);

  const argsStr = JSON.stringify(args, null, 2);
  const argsTruncated = argsStr.length > 200;
  const argsDisplay = argsExpanded || !argsTruncated ? argsStr : truncateJson(args, 200);

  const resultStr = result != null ? JSON.stringify(result, null, 2) : '';
  const resultTruncated = resultStr.length > 200;
  const resultDisplay = resultExpanded || !resultTruncated ? resultStr : truncateJson(result, 200);

  const Icon = TOOL_ICONS[tool] ?? Wrench;
  const StatusIcon = STATUS_ICON[status];
  const isSpinning = status === 'streaming' || status === 'pending';

  return (
    <div className={`bg-card/60 rounded border-l-2 ${statusColorMap[status]} px-3 py-2 space-y-1.5`}>
      <div className="flex items-center gap-2 flex-wrap">
        <Icon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        <span className="text-sm font-mono text-foreground">{tool}</span>
        <Badge variant={statusBadgeVariant[status]}>
          <span className="flex items-center gap-1">
            <StatusIcon className={`w-3 h-3 ${isSpinning ? 'animate-spin' : ''}`} />
            {statusText[status]}
          </span>
        </Badge>
        {startedAt && (status === 'streaming' || status === 'done' || status === 'error') && (
          <span className={`text-[10px] font-mono tabular-nums ${status === 'streaming' ? 'text-primary' : 'text-muted-foreground'}`}>
            · {formatMs(elapsed)}
          </span>
        )}
      </div>

      <details className="text-xs" onToggle={(e) => setArgsExpanded((e.target as HTMLDetailsElement).open)}>
        <summary className="flex items-center gap-1.5 cursor-pointer text-muted-foreground hover:text-foreground select-none list-none">
          {argsExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          <Hash className="w-3 h-3" />
          <span className="font-medium uppercase tracking-wider text-[10px]">Args</span>
          {argsTruncated && !argsExpanded && <span className="text-[10px] text-muted-foreground ml-1">(truncated)</span>}
        </summary>
        <pre className="mt-1.5 font-mono text-[11px] text-muted-foreground whitespace-pre-wrap break-all bg-muted/60 rounded p-2 max-h-48 overflow-y-auto">
          {argsDisplay}
        </pre>
      </details>

      {(status === 'done' || status === 'error') && (
        <details className="text-xs" onToggle={(e) => setResultExpanded((e.target as HTMLDetailsElement).open)}>
          <summary className="flex items-center gap-1.5 cursor-pointer text-muted-foreground hover:text-foreground select-none list-none">
            {resultExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <span className="font-medium uppercase tracking-wider text-[10px]">
              {status === 'error' ? 'Error' : 'Result'}
            </span>
            {status === 'error' && error && !resultExpanded && (
              <span className="text-[10px] text-destructive truncate ml-1 max-w-[200px]">{error}</span>
            )}
            {resultTruncated && !resultExpanded && status !== 'error' && (
              <span className="text-[10px] text-muted-foreground ml-1">(truncated)</span>
            )}
          </summary>
          <pre className={`mt-1.5 font-mono text-[11px] whitespace-pre-wrap break-all rounded p-2 max-h-64 overflow-y-auto ${
            status === 'error' ? 'text-destructive bg-muted/60 border border-destructive/30' : 'text-muted-foreground bg-muted/60'
          }`}>
            {status === 'error' ? error : resultDisplay}
          </pre>
        </details>
      )}
    </div>
  );
}
