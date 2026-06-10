/**
 * PaperForm — input form for starting paper extraction.
 *
 * Fields: paper_id, source_type (pdf/url), source_ref, paper_content.
 * Compact single-row layout matching yy-design-ui principles.
 */

import { useState } from 'react';
import { FileText, Link2, Send } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '../ui/Button';

// ─── Types ──────────────────────────────────────────────────

interface PaperFormProps {
  onSubmit: (req: {
    paper_id: string;
    source_type: 'pdf' | 'url';
    source_ref: string;
    paper_content: string;
  }) => Promise<void>;
  className?: string;
}

// ─── Component ──────────────────────────────────────────────

export function PaperForm({ onSubmit, className }: PaperFormProps) {
  const [paperId, setPaperId] = useState('');
  const [sourceType, setSourceType] = useState<'pdf' | 'url'>('pdf');
  const [sourceRef, setSourceRef] = useState('');
  const [paperContent, setPaperContent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = paperId.trim() && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        paper_id: paperId.trim(),
        source_type: sourceType,
        source_ref: sourceRef.trim(),
        paper_content: paperContent,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={cn('space-y-3', className)}>
      <div className="grid grid-cols-4 gap-2">
        <input
          type="text"
          value={paperId}
          onChange={(e) => setPaperId(e.target.value)}
          placeholder="Paper ID (e.g. arxiv-2501.12345)"
          className="col-span-1 px-3 py-2 bg-muted border border-border rounded-lg
            text-sm text-foreground placeholder-muted-foreground
            focus:outline-none focus:border-primary font-mono"
          disabled={submitting}
        />

        <div className="col-span-1 flex gap-1">
          <button
            onClick={() => setSourceType('pdf')}
            disabled={submitting}
            className={cn(
              'flex-1 px-2 py-2 rounded-lg text-xs font-medium transition-colors',
              sourceType === 'pdf'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:text-foreground',
            )}
          >
            <FileText className="w-3 h-3 inline mr-1" />
            PDF
          </button>
          <button
            onClick={() => setSourceType('url')}
            disabled={submitting}
            className={cn(
              'flex-1 px-2 py-2 rounded-lg text-xs font-medium transition-colors',
              sourceType === 'url'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:text-foreground',
            )}
          >
            <Link2 className="w-3 h-3 inline mr-1" />
            URL
          </button>
        </div>

        <input
          type="text"
          value={sourceRef}
          onChange={(e) => setSourceRef(e.target.value)}
          placeholder={sourceType === 'pdf' ? '/path/to/paper.pdf' : 'https://...'}
          className="col-span-1 px-3 py-2 bg-muted border border-border rounded-lg
            text-sm text-foreground placeholder-muted-foreground
            focus:outline-none focus:border-primary"
          disabled={submitting}
        />

        <Button
          onClick={handleSubmit}
          disabled={!canSubmit}
          variant="primary"
          size="sm"
          className="col-span-1"
        >
          {submitting ? (
            <span className="animate-pulse">提取中...</span>
          ) : (
            <>
              <Send className="w-3 h-3 inline mr-1" />
              开始提取
            </>
          )}
        </Button>
      </div>

      <textarea
        value={paperContent}
        onChange={(e) => setPaperContent(e.target.value)}
        placeholder="粘贴论文内容（可选，留空则从 source_ref 读取）..."
        className="w-full h-20 px-3 py-2 bg-muted border border-border rounded-lg
          text-sm text-foreground placeholder-muted-foreground
          focus:outline-none focus:border-primary resize-none font-mono"
        disabled={submitting}
      />

      {error && (
        <div className="text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-lg p-2">
          {error}
        </div>
      )}
    </div>
  );
}