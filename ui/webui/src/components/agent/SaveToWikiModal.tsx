import { useState, useCallback } from 'react';
import { saveToWiki } from '../../lib/autoresearch-api';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog';

interface Props {
  sessionId: string;
  query?: string;
  onClose: () => void;
  onSaved?: () => void;
}

function generatePageName(query: string): string {
  const slug = query
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);
  return `research/${slug || 'untitled'}`;
}

export function SaveToWikiModal({ sessionId, query, onClose, onSaved }: Props) {
  const [pageName, setPageName] = useState(() => generatePageName(query || ''));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<{ status: string; message?: string; confirmation_id?: string } | null>(null);

  const handleSave = useCallback(async () => {
    if (!pageName.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await saveToWiki(sessionId, pageName.trim());
      setResult(res);
      onSaved?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId, pageName, onSaved]);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        className="max-w-md sm:max-w-md"
        showCloseButton={false}
        onClick={(e) => e.stopPropagation()}
      >
        <DialogHeader>
          <DialogTitle>Save to Wiki</DialogTitle>
          <DialogDescription>
            Report will be saved as a wiki page. Sources and synthesis will also be saved.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Page Name</label>
            <input
              value={pageName}
              onChange={e => setPageName(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-muted border border-border rounded focus:outline-none focus:border-primary"
              placeholder="research/my-topic"
            />
          </div>
          {error && <div className="text-xs text-red-400">{error}</div>}
          {result && (
            <div className="text-xs text-green-400">
              {result.message || result.status}
              {result.confirmation_id && (
                <span className="ml-1">— Confirmation ID: {result.confirmation_id}</span>
              )}
            </div>
          )}
        </div>

        <div className="flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button
              onClick={handleSave}
              disabled={loading || !pageName.trim()}
              className="px-3 py-1.5 text-xs bg-primary text-white rounded hover:opacity-90 disabled:opacity-50"
            >
              {loading ? 'Saving...' : 'Confirm & Save'}
            </button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
