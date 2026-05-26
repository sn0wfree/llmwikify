import { Badge } from './Badge';

interface ToolCardProps {
  tool: string;
  args: Record<string, unknown>;
  status: 'pending' | 'done' | 'error';
}

const statusColorMap = {
  pending: 'border-yellow-500',
  done: 'border-green-500',
  error: 'border-red-500',
};

const statusBadgeVariant = {
  pending: 'warning' as const,
  done: 'success' as const,
  error: 'error' as const,
};

const statusText = {
  pending: 'running',
  done: 'done',
  error: 'error',
};

export function ToolCard({ tool, args, status }: ToolCardProps) {
  return (
    <div className={`
      bg-[var(--bg-secondary)] rounded border-l-4
      ${statusColorMap[status]}
      p-3
    `}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-medium text-[var(--accent)]">{tool}</span>
        <Badge variant={statusBadgeVariant[status]}>{statusText[status]}</Badge>
      </div>
      <div className="text-xs text-[var(--text-secondary)] font-mono overflow-x-auto">
        {JSON.stringify(args, null, 2)}
      </div>
    </div>
  );
}