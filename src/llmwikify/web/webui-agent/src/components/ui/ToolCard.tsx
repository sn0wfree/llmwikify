import { useState } from 'react';
import { Badge } from './Badge';

type ToolStatus = 'pending' | 'streaming' | 'done' | 'error';

interface ToolCardProps {
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  result?: unknown;
  error?: string;
}

const statusColorMap: Record<ToolStatus, string> = {
  pending: 'border-yellow-500',
  streaming: 'border-blue-500',
  done: 'border-green-500',
  error: 'border-red-500',
};

const statusBadgeVariant: Record<ToolStatus, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  pending: 'warning',
  streaming: 'info',
  done: 'success',
  error: 'error',
};

const statusText: Record<ToolStatus, string> = {
  pending: 'pending',
  streaming: 'running',
  done: 'done',
  error: 'error',
};

const TOOL_ICONS: Record<string, string> = {
  wiki_search: '🔍',
  wiki_read_page: '📄',
  wiki_write_page: '✏️',
  wiki_edit_page: '📝',
  wiki_create_page: '🆕',
  wiki_delete_page: '🗑️',
  wiki_analyze_source: '🧠',
  wiki_suggest_synthesis: '🔗',
  confirmation_required: '⚠️',
};

function getToolIcon(tool: string): string {
  return TOOL_ICONS[tool] || '⚙️';
}

function truncateJson(obj: unknown, maxLen = 300): string {
  const str = JSON.stringify(obj, null, 2);
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + '...\n}';
}

export function ToolCard({ tool, args, status, result, error }: ToolCardProps) {
  const [argsExpanded, setArgsExpanded] = useState(false);
  const [resultExpanded, setResultExpanded] = useState(false);

  const argsStr = JSON.stringify(args, null, 2);
  const argsTruncated = argsStr.length > 300;
  const argsDisplay = argsExpanded || !argsTruncated ? argsStr : argsStr.slice(0, 300) + '\n...';

  const resultStr = result != null ? JSON.stringify(result, null, 2) : '';
  const resultTruncated = resultStr.length > 200;
  const resultDisplay = resultExpanded || !resultTruncated ? resultStr : resultStr.slice(0, 200) + '\n...';

  return (
    <div className={`
      bg-[var(--bg-secondary)] rounded border-l-4
      ${statusColorMap[status]}
      p-3 space-y-2
    `}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-base" title={tool}>{getToolIcon(tool)}</span>
        <span className="text-sm font-medium text-[var(--accent)]">{tool}</span>
        <Badge variant={statusBadgeVariant[status]}>
          {status === 'streaming' ? (
            <span className="flex items-center gap-1">
              <span className="thinking-dots">
                <span>·</span><span>·</span><span>·</span>
              </span>
              {statusText[status]}
            </span>
          ) : (
            statusText[status]
          )}
        </Badge>
        {status === 'error' && error && (
          <span className="text-xs text-red-400 ml-auto">click to expand</span>
        )}
      </div>

      <div className="text-xs">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[var(--text-secondary)] font-medium uppercase tracking-wide text-[10px]">Args</span>
          {argsTruncated && (
            <button
              onClick={() => setArgsExpanded(!argsExpanded)}
              className="text-[var(--accent)] text-[10px] hover:underline"
            >
              {argsExpanded ? 'collapse' : 'expand'}
            </button>
          )}
        </div>
        <pre className="font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-all bg-[var(--bg-tertiary)] rounded p-2 max-h-48 overflow-y-auto">
          {argsDisplay}
        </pre>
      </div>

      {(status === 'done' || status === 'error') && (
        <div className="text-xs">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[var(--text-secondary)] font-medium uppercase tracking-wide text-[10px]">
              {status === 'error' ? 'Error' : 'Result'}
            </span>
            {resultTruncated && status !== 'error' && (
              <button
                onClick={() => setResultExpanded(!resultExpanded)}
                className="text-[var(--accent)] text-[10px] hover:underline"
              >
                {resultExpanded ? 'collapse' : 'expand'}
              </button>
            )}
          </div>
          <pre className={`
            font-mono whitespace-pre-wrap break-all bg-[var(--bg-tertiary)] rounded p-2 max-h-64 overflow-y-auto
            ${status === 'error' ? 'text-red-400 border border-red-500/30' : 'text-[var(--text-secondary)]'}
          `}>
            {status === 'error' ? error : resultDisplay}
          </pre>
        </div>
      )}
    </div>
  );
}