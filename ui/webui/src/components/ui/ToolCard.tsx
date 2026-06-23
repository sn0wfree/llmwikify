import { useState, useEffect } from 'react';
import {
  Search, FileText, Pencil, FileEdit, FilePlus, Trash2,
  Brain, Link2, AlertTriangle, Wrench, Loader2,
  CheckCircle2, XCircle, ChevronDown, ChevronRight, Hash,
  Copy, Check,
} from 'lucide-react';
import { cn } from '@/lib/utils';

type ToolStatus = 'pending' | 'streaming' | 'done' | 'error' | 'executed' | 'confirmation_required';

interface ToolCardProps {
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  result?: unknown;
  error?: string;
  startedAt?: number;
  finishedAt?: number;
  duration_ms?: number;
}

const TOOL_ICONS: Record<string, typeof Wrench> = {
  wiki_search: Search, wiki_read_page: FileText, wiki_write_page: Pencil,
  wiki_edit_page: FileEdit, wiki_create_page: FilePlus, wiki_delete_page: Trash2,
  wiki_analyze_source: Brain, wiki_suggest_synthesis: Link2,
  confirmation_required: AlertTriangle,
};

const STATUS_ICON: Record<ToolStatus, typeof Loader2> = {
  pending: Loader2, streaming: Loader2, done: CheckCircle2, error: XCircle,
  executed: CheckCircle2, confirmation_required: AlertTriangle,
};

const statusColorMap: Record<ToolStatus, string> = {
  pending: 'border-warning/40',
  streaming: 'border-primary/50',
  done: 'border-success/40',
  error: 'border-destructive/50',
  executed: 'border-success/40',
  confirmation_required: 'border-warning/40',
};

const statusBadgeVariant: Record<ToolStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  pending: 'outline', streaming: 'default', done: 'secondary', error: 'destructive',
  executed: 'secondary', confirmation_required: 'outline',
};

const statusText: Record<ToolStatus, string> = {
  pending: 'pending', streaming: 'running', done: 'done', error: 'error',
  executed: 'done', confirmation_required: 'confirm',
};

const statusDotColor: Record<ToolStatus, string> = {
  pending: 'bg-warning',
  streaming: 'bg-primary animate-stage-pulse',
  done: 'bg-success',
  error: 'bg-destructive',
  executed: 'bg-success',
  confirmation_required: 'bg-warning',
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
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [startedAt, finishedAt]);
  return startedAt ? (finishedAt ?? now) - startedAt : 0;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* */ }
  };
  return (
    <button
      onClick={handleCopy}
      className="p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-white/[0.06] transition-colors"
      title="Copy"
      aria-label="Copy JSON"
    >
      {copied ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

export function ToolCard({ tool, args, status, result, error, startedAt, finishedAt, duration_ms }: ToolCardProps) {
  const [argsExpanded, setArgsExpanded] = useState(false);
  const [resultExpanded, setResultExpanded] = useState(false);
  // Prefer backend-reported duration_ms; fall back to local elapsed calculation
  const localElapsed = useElapsedMs(startedAt, finishedAt);
  const elapsed = duration_ms ?? localElapsed;

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
    <div className={cn(
      'relative pl-5 py-1 animate-slide-up',
    )}>
      {/* Timeline line */}
      <div className="absolute left-[5px] top-2 bottom-0 w-px bg-border" />
      {/* Status dot */}
      <div className={cn(
        'absolute left-0 top-2 w-2.5 h-2.5 rounded-full ring-2 ring-background',
        statusDotColor[status],
      )} />

      <div className={cn(
        'rounded-lg border bg-card/40 backdrop-blur-sm overflow-hidden',
        statusColorMap[status],
      )}>
        {/* Header */}
        <div className="flex items-center gap-2 px-3 py-2">
          <Icon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs font-mono text-foreground flex-1 truncate">{tool}</span>
          <span className="flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full border border-border/60 bg-background/40">
            <StatusIcon className={cn('w-2.5 h-2.5', isSpinning && 'animate-spin')} />
            <span className="text-muted-foreground">{statusText[status]}</span>
          </span>
          {startedAt && (
            <span className={cn(
              'text-[10px] font-mono tabular-nums',
              status === 'streaming' ? 'text-primary' : 'text-muted-foreground',
            )}>
              {formatMs(elapsed)}
            </span>
          )}
        </div>

        {/* Args */}
        <div className="border-t border-border/30">
          <button
            onClick={() => setArgsExpanded(!argsExpanded)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors w-full text-left"
          >
            {argsExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <Hash className="w-3 h-3" />
            <span className="font-semibold uppercase tracking-wider">Args</span>
            {argsTruncated && !argsExpanded && <span className="text-muted-foreground/60">({argsStr.length} chars)</span>}
            <span className="ml-auto">
              <CopyButton text={argsStr} />
            </span>
          </button>
          {argsExpanded && (
            <pre className="font-mono text-[11px] text-muted-foreground whitespace-pre-wrap break-all bg-muted/40 px-3 py-2 max-h-48 overflow-y-auto border-t border-border/30">
              {argsDisplay}
            </pre>
          )}
        </div>

        {/* Result / Error */}
        {(status === 'done' || status === 'error') && (
          <div className="border-t border-border/30">
            <button
              onClick={() => setResultExpanded(!resultExpanded)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors w-full text-left"
            >
              {resultExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              <span className="font-semibold uppercase tracking-wider">
                {status === 'error' ? 'Error' : 'Result'}
              </span>
              {status === 'error' && error && !resultExpanded && (
                <span className="text-destructive truncate ml-1 max-w-[200px]">{error}</span>
              )}
              {resultTruncated && !resultExpanded && status !== 'error' && (
                <span className="text-muted-foreground/60">({resultStr.length} chars)</span>
              )}
              <span className="ml-auto">
                <CopyButton text={status === 'error' ? (error || '') : resultStr} />
              </span>
            </button>
            {resultExpanded && (
              <pre className={cn(
                'font-mono text-[11px] whitespace-pre-wrap break-all px-3 py-2 max-h-64 overflow-y-auto border-t border-border/30',
                status === 'error'
                  ? 'text-destructive bg-destructive/5'
                  : 'text-muted-foreground bg-muted/40',
              )}>
                {status === 'error' ? error : resultDisplay}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
