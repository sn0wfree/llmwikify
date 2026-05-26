import { useState } from 'react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';

interface ImpactDisplayProps {
  impact: Record<string, unknown>;
}

function ImpactDisplay({ impact }: ImpactDisplayProps) {
  if (!impact || Object.keys(impact).length === 0) {
    return <span className="text-xs text-[var(--text-secondary)]">No impact details available</span>;
  }

  const lines: string[] = [];
  if (impact.pages) {
    const pages = Array.isArray(impact.pages) ? impact.pages : [impact.pages];
    lines.push(`Pages: ${pages.join(', ')}`);
  }
  if (impact.action_type) {
    lines.push(`Action: ${String(impact.action_type)}`);
  }
  if (impact.description) {
    lines.push(`Description: ${String(impact.description)}`);
  }

  return (
    <div className="space-y-1">
      {lines.map((line, i) => (
        <div key={i} className="text-xs text-[var(--text-secondary)]">{line}</div>
      ))}
    </div>
  );
}

interface ConfirmationModalProps {
  confirmationId: string;
  tool: string;
  args: Record<string, unknown>;
  impact: Record<string, unknown>;
  group?: string;
  onApprove: () => void;
  onReject: () => void;
  loading?: boolean;
}

export function ConfirmationModal({
  confirmationId,
  tool,
  args,
  impact,
  group,
  onApprove,
  onReject,
  loading = false,
}: ConfirmationModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md mx-4 bg-[var(--bg-secondary)] rounded-lg shadow-xl border border-[var(--border)] overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--warning)]/10">
          <div className="flex items-center gap-2">
            <span className="text-base">⚠️</span>
            <span className="text-sm font-semibold text-[var(--warning)]">Confirmation Required</span>
          </div>
          {group && (
            <div className="text-xs text-[var(--text-secondary)] mt-1 ml-6">
              Group: {group}
            </div>
          )}
        </div>

        <div className="p-4 space-y-4">
          <div>
            <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Tool</div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[var(--accent)]">{tool}</span>
              <Badge variant="warning">requires approval</Badge>
            </div>
          </div>

          <div>
            <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Arguments</div>
            <pre className="text-xs font-mono bg-[var(--bg-tertiary)] rounded p-2 max-h-32 overflow-y-auto text-[var(--text-secondary)]">
              {JSON.stringify(args, null, 2)}
            </pre>
          </div>

          <div>
            <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Impact</div>
            <div className="bg-[var(--bg-tertiary)] rounded p-2">
              <ImpactDisplay impact={impact} />
            </div>
          </div>
        </div>

        <div className="px-4 py-3 border-t border-[var(--border)] flex gap-3 justify-end">
          <Button
            onClick={onReject}
            disabled={loading}
            variant="secondary"
          >
            Reject
          </Button>
          <Button
            onClick={onApprove}
            disabled={loading}
          >
            {loading ? 'Approving...' : 'Approve'}
          </Button>
        </div>
      </div>
    </div>
  );
}