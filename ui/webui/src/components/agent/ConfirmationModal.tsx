import { useState, useEffect, useCallback } from 'react';
import { api } from '../../api';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

interface ConfirmationModalProps {
  confirmationId: string;
  tool: string;
  args: Record<string, unknown>;
  impact: Record<string, unknown>;
  group?: string;
  createdAt?: string;
  onApprove: (editedArgs?: Record<string, unknown>) => void;
  onReject: () => void;
  loading?: boolean;
}

function WikiWriteView({ args, editing, editedArgs, setEditedArgs }: {
  args: Record<string, unknown>;
  editing: boolean;
  editedArgs: Record<string, unknown>;
  setEditedArgs: (a: Record<string, unknown>) => void;
}) {
  const pageName = String(editedArgs.page_name || args.page_name || '');
  const content = String(editedArgs.content || args.content || '');

  return (
    <div className="space-y-3">
      <div>
        <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Page</div>
        <div className="text-sm font-medium text-[var(--accent)]">{pageName}</div>
      </div>
      <div>
        <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">
          Content ({content.length} chars)
        </div>
        {editing ? (
          <textarea
            value={content}
            onChange={e => setEditedArgs({ ...editedArgs, content: e.target.value })}
            className="w-full h-64 px-3 py-2 text-xs font-mono bg-[var(--bg-tertiary)] border border-[var(--border)] rounded focus:outline-none focus:border-[var(--accent)] resize-y"
          />
        ) : (
          <div className="max-h-64 overflow-y-auto bg-[var(--bg-tertiary)] rounded p-3">
            <div className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed">
              {content.slice(0, 3000)}
              {content.length > 3000 && <span className="text-[var(--accent)]">... ({content.length - 3000} more chars)</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ResearchSaveView({ args }: { args: Record<string, unknown> }) {
  const [sessionData, setSessionData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const sessionId = String(args.session_id || '');

  useEffect(() => {
    if (!sessionId) { setLoading(false); return; }
    setLoading(true);
    api.research.get(sessionId)
      .then(data => {
        let result = data.result;
        if (typeof result === 'string') {
          try { result = JSON.parse(result); } catch { /* keep as string */ }
        }
        setSessionData({ ...data, parsedResult: result });
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [sessionId]);

  const pageName = String(args.page_name || '(auto-generated)');
  const result = sessionData?.parsedResult as Record<string, unknown> | undefined;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <div>
          <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Target Page</div>
          <div className="text-sm font-medium text-[var(--accent)]">{pageName}</div>
        </div>
        {sessionData?.query && (
          <div className="flex-1">
            <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Research Query</div>
            <div className="text-sm text-[var(--text-primary)]">{String(sessionData.query)}</div>
          </div>
        )}
      </div>

      {loading && <div className="text-xs text-[var(--text-secondary)]">Loading report...</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}

      {result && (
        <>
          {result.quality_score !== undefined && (
            <div className="flex items-center gap-4 text-xs">
              <span className="text-[var(--text-secondary)]">Quality:</span>
              <span className={`font-bold ${Number(result.quality_score) >= 7 ? 'text-green-400' : Number(result.quality_score) >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
                {String(result.quality_score)}/10
              </span>
              {result.rounds !== undefined && (
                <span className="text-[var(--text-secondary)]">Rounds: {String(result.rounds)}</span>
              )}
            </div>
          )}

          {result.markdown && (
            <div>
              <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">
                Report ({String(result.markdown).length} chars)
              </div>
              <div className="max-h-48 overflow-y-auto bg-[var(--bg-tertiary)] rounded p-3">
                <div className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed">
                  {String(result.markdown).slice(0, 4000)}
                  {String(result.markdown).length > 4000 && (
                    <span className="text-[var(--accent)]">... (truncated)</span>
                  )}
                </div>
              </div>
            </div>
          )}

          {result.sources && Array.isArray(result.sources) && result.sources.length > 0 && (
            <div>
              <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">
                Sources ({result.sources.length})
              </div>
              <div className="max-h-24 overflow-y-auto space-y-1">
                {result.sources.map((src: Record<string, unknown>, i: number) => (
                  <div key={i} className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
                    <span className="w-4 text-center shrink-0">{i + 1}.</span>
                    <span className="truncate">{String(src.title || src.url || '')}</span>
                    {src.source_type && (
                      <span className="px-1 py-px rounded text-[9px] bg-blue-500/20 text-blue-400 shrink-0">
                        {String(src.source_type)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.synthesis_summary && (
            <div>
              <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Synthesis Summary</div>
              <div className="text-xs text-[var(--text-secondary)] bg-[var(--bg-tertiary)] rounded p-2 max-h-20 overflow-y-auto whitespace-pre-wrap">
                {String(result.synthesis_summary)}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SynthesizeView({ args, editing, editedArgs, setEditedArgs }: {
  args: Record<string, unknown>;
  editing: boolean;
  editedArgs: Record<string, unknown>;
  setEditedArgs: (a: Record<string, unknown>) => void;
}) {
  const query = String(editedArgs.query || args.query || '');
  const answer = String(editedArgs.answer || args.answer || '');
  const sourcePages = (editedArgs.source_pages || args.source_pages || []) as string[];
  const pageName = String(editedArgs.page_name || args.page_name || '(auto-generated)');

  return (
    <div className="space-y-3">
      <div>
        <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Target Page</div>
        <div className="text-sm font-medium text-[var(--accent)]">{pageName}</div>
      </div>
      <div>
        <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Query</div>
        {editing ? (
          <input
            value={query}
            onChange={e => setEditedArgs({ ...editedArgs, query: e.target.value })}
            className="w-full px-3 py-2 text-sm bg-[var(--bg-tertiary)] border border-[var(--border)] rounded focus:outline-none focus:border-[var(--accent)]"
          />
        ) : (
          <div className="text-sm text-[var(--text-primary)]">{query}</div>
        )}
      </div>
      <div>
        <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">
          Answer ({answer.length} chars)
        </div>
        {editing ? (
          <textarea
            value={answer}
            onChange={e => setEditedArgs({ ...editedArgs, answer: e.target.value })}
            className="w-full h-40 px-3 py-2 text-xs font-mono bg-[var(--bg-tertiary)] border border-[var(--border)] rounded focus:outline-none focus:border-[var(--accent)] resize-y"
          />
        ) : (
          <div className="max-h-40 overflow-y-auto bg-[var(--bg-tertiary)] rounded p-3">
            <div className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed">
              {answer.slice(0, 3000)}
              {answer.length > 3000 && <span className="text-[var(--accent)]">... (truncated)</span>}
            </div>
          </div>
        )}
      </div>
      {sourcePages.length > 0 && (
        <div>
          <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Source Pages</div>
          <div className="flex flex-wrap gap-1">
            {sourcePages.map((p, i) => (
              <span key={i} className="text-xs px-1.5 py-0.5 bg-[var(--bg-tertiary)] rounded text-[var(--text-secondary)]">{p}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function DefaultView({ args, editing, editedArgs, setEditedArgs }: {
  args: Record<string, unknown>;
  editing: boolean;
  editedArgs: Record<string, unknown>;
  setEditedArgs: (a: Record<string, unknown>) => void;
}) {
  return (
    <div>
      <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Arguments</div>
      {editing ? (
        <textarea
          value={JSON.stringify(editedArgs, null, 2)}
          onChange={e => {
            try { setEditedArgs(JSON.parse(e.target.value)); } catch { /* ignore */ }
          }}
          className="w-full h-48 px-3 py-2 text-xs font-mono bg-[var(--bg-tertiary)] border border-[var(--border)] rounded focus:outline-none focus:border-[var(--accent)] resize-y"
        />
      ) : (
        <pre className="text-xs font-mono bg-[var(--bg-tertiary)] rounded p-2 max-h-48 overflow-y-auto text-[var(--text-secondary)] whitespace-pre-wrap">
          {JSON.stringify(args, null, 2)}
        </pre>
      )}
    </div>
  );
}

function ImpactSummary({ impact }: { impact: Record<string, unknown> }) {
  if (!impact || Object.keys(impact).length === 0) return null;
  const items: { label: string; value: string }[] = [];
  if (impact.page) items.push({ label: 'Page', value: String(impact.page) });
  if (impact.source) items.push({ label: 'Source', value: String(impact.source) });
  if (impact.change_type) items.push({ label: 'Action', value: String(impact.change_type) });
  if (impact.chars) items.push({ label: 'Size', value: `${impact.chars} chars` });
  if (impact.description) items.push({ label: 'Description', value: String(impact.description) });
  if (impact.query) items.push({ label: 'Query', value: String(impact.query) });
  if (impact.relations_count) items.push({ label: 'Relations', value: String(impact.relations_count) });

  if (items.length === 0) return null;
  return (
    <div className="bg-[var(--bg-tertiary)] rounded p-2 space-y-0.5">
      {items.map((item, i) => (
        <div key={i} className="text-xs text-[var(--text-secondary)]">
          <span className="font-medium">{item.label}:</span> {item.value}
        </div>
      ))}
    </div>
  );
}

export function ConfirmationModal({
  confirmationId,
  tool,
  args,
  impact,
  group,
  createdAt,
  onApprove,
  onReject,
  loading = false,
}: ConfirmationModalProps) {
  const [editing, setEditing] = useState(false);
  const [editedArgs, setEditedArgs] = useState<Record<string, unknown>>(args);

  useEffect(() => { setEditedArgs(args); setEditing(false); }, [args]);

  const hasChanges = JSON.stringify(editedArgs) !== JSON.stringify(args);

  const handleApprove = useCallback(() => {
    onApprove(hasChanges ? editedArgs : undefined);
  }, [onApprove, hasChanges, editedArgs]);

  const renderToolView = () => {
    const common = { args, editing, editedArgs, setEditedArgs };
    switch (tool) {
      case 'wiki_write_page':
        return <WikiWriteView {...common} />;
      case 'research_save_to_wiki':
        return <ResearchSaveView args={args} />;
      case 'wiki_synthesize':
        return <SynthesizeView {...common} />;
      default:
        return <DefaultView {...common} />;
    }
  };

  const canEdit = tool === 'wiki_write_page' || tool === 'wiki_synthesize' || tool === 'graph_write';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onReject}>
      <div className="w-full max-w-lg mx-4 bg-[var(--bg-secondary)] rounded-lg shadow-xl border border-[var(--border)] overflow-hidden max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--warning)]/10 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-base">⚠️</span>
              <span className="text-sm font-semibold text-[var(--warning)]">Confirmation Required</span>
            </div>
            <div className="flex items-center gap-2">
              {editing && (
                <button
                  onClick={() => { setEditedArgs(args); setEditing(false); }}
                  className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                >
                  Reset
                </button>
              )}
              {canEdit && (
                <button
                  onClick={() => setEditing(!editing)}
                  className={`text-xs px-2 py-0.5 rounded ${editing ? 'bg-[var(--accent)] text-white' : 'text-[var(--accent)] hover:bg-[var(--accent)]/10'}`}
                >
                  {editing ? 'Editing' : 'Edit'}
                </button>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3 mt-1 ml-6 text-xs text-[var(--text-secondary)]">
            {group && <span>Group: {group.replace(/_/g, ' ')}</span>}
            {createdAt && <span>· {new Date(createdAt).toLocaleString()}</span>}
          </div>
        </div>

        <div className="p-4 space-y-4 overflow-y-auto flex-1">
          <div>
            <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Tool</div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[var(--accent)]">{tool}</span>
              <Badge variant="warning">requires approval</Badge>
              {hasChanges && <Badge variant="info">modified</Badge>}
            </div>
          </div>

          {renderToolView()}

          <div>
            <div className="text-xs text-[var(--text-secondary)] uppercase tracking-wide mb-1">Impact</div>
            <ImpactSummary impact={impact} />
          </div>
        </div>

        <div className="px-4 py-3 border-t border-[var(--border)] flex gap-3 justify-end shrink-0">
          <Button onClick={onReject} disabled={loading} variant="secondary">
            Reject
          </Button>
          <Button onClick={handleApprove} disabled={loading}>
            {loading ? 'Approving...' : hasChanges ? 'Approve & Save Edits' : 'Approve'}
          </Button>
        </div>
      </div>
    </div>
  );
}
