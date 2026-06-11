import { memo, useMemo, useState, useEffect } from 'react';
import {
  Cpu,
  Wifi,
  Wrench,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertCircle,
  Activity,
  Clock,
  Hash,
  MessageSquare,
  Coins,
} from 'lucide-react';

type ToolStatus = 'pending' | 'streaming' | 'done' | 'error';
type ConnectionState = 'idle' | 'live' | 'error';

interface ToolCall {
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  error?: string;
  status: ToolStatus;
  startedAt?: number;
  finishedAt?: number;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  toolCalls?: ToolCall[];
}

interface ToolsRailProps {
  messages: Message[];
  currentToolCalls: ToolCall[];
  modelName: string;
  connectionState: ConnectionState;
  sessionId: string | null;
  tokenEstimate: number;
}

const STATE_TONE: Record<ConnectionState, string> = {
  idle: 'text-text-secondary',
  live: 'text-green-500',
  error: 'text-destructive',
};

const STATE_DOT: Record<ConnectionState, string> = {
  idle: 'bg-text-secondary/40',
  live: 'bg-green-500',
  error: 'bg-destructive',
};

const STATE_LABEL: Record<ConnectionState, string> = {
  idle: 'idle',
  live: 'live',
  error: 'error',
};

const STATUS_ICON: Record<ToolStatus, typeof Loader2> = {
  pending: Loader2,
  streaming: Loader2,
  done: CheckCircle2,
  error: XCircle,
};

const STATUS_TONE: Record<ToolStatus, string> = {
  pending: 'text-yellow-500',
  streaming: 'text-primary',
  done: 'text-green-500',
  error: 'text-destructive',
};

function formatTimeShort(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function relativeTime(iso: string): string {
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const min = Math.floor(ms / 60000);
  const sec = ((ms % 60000) / 1000).toFixed(0);
  return `${min}m${sec}s`;
}

function RailElapsed({ startedAt, finishedAt }: { startedAt?: number; finishedAt?: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!startedAt || finishedAt) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [startedAt, finishedAt]);
  if (!startedAt) return null;
  const elapsed = (finishedAt ?? now) - startedAt;
  return (
    <span className={`text-[10px] font-mono tabular-nums ${finishedAt ? 'text-muted-foreground/60' : 'text-primary'}`}>
      {finishedAt ? formatMs(elapsed) : `${formatMs(elapsed)}…`}
    </span>
  );
}

function ToolsRailImpl({
  messages,
  currentToolCalls,
  modelName,
  connectionState,
  sessionId,
  tokenEstimate,
}: ToolsRailProps) {
  const allTools = useMemo<ToolCall[]>(() => {
    const fromMessages = messages
      .flatMap((m) => m.toolCalls ?? [])
      .map((tc) => ({ ...tc }));
    return [...fromMessages, ...currentToolCalls];
  }, [messages, currentToolCalls]);

  const stats = useMemo(() => {
    const done = allTools.filter((t) => t.status === 'done').length;
    const errored = allTools.filter((t) => t.status === 'error').length;
    return { total: allTools.length, done, errored };
  }, [allTools]);

  return (
    <aside
      className="hidden lg:flex flex-col w-80 shrink-0 border-l border-border bg-card/40 backdrop-blur-sm"
      aria-label="Tools and status"
    >
      <div className="p-3 border-b border-border space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Session
          </span>
          {sessionId ? (
            <span className="text-xs font-mono text-muted-foreground">
              #{sessionId.slice(0, 8)}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground italic">new</span>
          )}
        </div>
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-muted/40 border border-border/40">
          <Cpu className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs font-mono truncate" title={modelName || 'No model configured'}>
            {modelName || 'No model configured'}
          </span>
        </div>
        <div className={`flex items-center gap-1.5 text-xs ${STATE_TONE[connectionState]}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${STATE_DOT[connectionState]}`} />
          <Wifi className="w-3 h-3" />
          <span>Connection: {STATE_LABEL[connectionState]}</span>
        </div>
      </div>

      <div className="px-3 py-2 border-b border-border flex items-center gap-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-1" title="Total messages in this session">
          <MessageSquare className="w-3 h-3" />
          <span className="font-mono">{messages.length}</span>
        </div>
        <div className="flex items-center gap-1" title="Total tool calls">
          <Wrench className="w-3 h-3" />
          <span className="font-mono">{stats.total}</span>
        </div>
        <div className="flex items-center gap-1" title="Successful tool calls">
          <CheckCircle2 className="w-3 h-3 text-green-500" />
          <span className="font-mono">{stats.done}</span>
        </div>
        {stats.errored > 0 && (
          <div className="flex items-center gap-1" title="Failed tool calls">
            <XCircle className="w-3 h-3 text-destructive" />
            <span className="font-mono">{stats.errored}</span>
          </div>
        )}
        {tokenEstimate > 0 && (
          <div className="flex items-center gap-1 ml-auto" title="Approximate token usage">
            <Coins className="w-3 h-3" />
            <span className="font-mono">
              {tokenEstimate < 1000 ? tokenEstimate : `${(tokenEstimate / 1000).toFixed(1)}k`}
            </span>
          </div>
        )}
      </div>

      {/* v0.40: Context window usage progress bar */}
      {tokenEstimate > 0 && (
        <div className="px-3 py-2 border-b border-border">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
              Context
            </span>
            <span className="text-[10px] font-mono text-muted-foreground">
              {tokenEstimate < 1000 ? tokenEstimate : `${(tokenEstimate / 1000).toFixed(1)}k`} / 128k
            </span>
          </div>
          <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full transition-all"
              style={{
                width: `${Math.min(100, (tokenEstimate / 128000) * 100)}%`,
                background:
                  (tokenEstimate / 128000) > 0.8
                    ? 'var(--destructive, #ef4444)'
                    : (tokenEstimate / 128000) > 0.5
                    ? 'var(--warning, #f59e0b)'
                    : 'var(--primary, #6366f1)',
              }}
            />
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        <div className="px-3 py-2 sticky top-0 bg-card/95 backdrop-blur-sm border-b border-border/40 z-10">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <Activity className="w-3 h-3" />
            Tool Timeline
          </span>
        </div>
        {allTools.length === 0 ? (
          <div className="p-4 text-xs text-muted-foreground text-center italic">
            No tools invoked yet
          </div>
        ) : (
          <ul className="py-1">
            {allTools.map((tc, idx) => {
              const Icon = STATUS_ICON[tc.status];
              return (
                <li
                  key={`${tc.tool}-${idx}`}
                  className="px-3 py-2 border-b border-border/30 hover:bg-muted/30 transition-colors"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Icon
                      className={`w-3.5 h-3.5 shrink-0 ${STATUS_TONE[tc.status]} ${
                        tc.status === 'streaming' || tc.status === 'pending' ? 'animate-spin' : ''
                      }`}
                    />
                    <span className="text-xs font-mono text-foreground truncate flex-1">
                      {tc.tool}
                    </span>
                    <RailElapsed startedAt={tc.startedAt} finishedAt={tc.finishedAt} />
                  </div>
                  {tc.error && (
                    <div className="mt-1 text-[10px] text-destructive truncate" title={tc.error}>
                      {tc.error}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="p-3 border-t border-border text-xs text-muted-foreground space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Clock className="w-3 h-3" />
          <span>
            {sessionId ? 'Last activity' : 'New session'}
          </span>
        </div>
        {messages.length > 0 && (
          <div className="font-mono text-[10px] pl-4">
            {relativeTime(messages[messages.length - 1].timestamp)}
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <Hash className="w-3 h-3" />
          <span>
            {stats.total === 0
              ? 'No tools yet'
              : `${stats.done}/${stats.total} succeeded`}
          </span>
        </div>
        {sessionId && messages.length > 0 && (
          <div className="font-mono text-[10px] pl-4 text-muted-foreground/60">
            started {formatTimeShort(messages[0].timestamp)}
          </div>
        )}
      </div>
    </aside>
  );
}

export const ToolsRail = memo(ToolsRailImpl);
