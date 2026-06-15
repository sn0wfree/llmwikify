/**
 * PaperForm — input form for starting paper extraction.
 *
 * v0.4.0 enhancements:
 * - source_type now has 3 options: pdf / url / raw
 * - "raw" mode: dropdown listing *.pdf files in <project>/raw/
 * - "📎 上传 PDF" button: multipart upload to /api/paper/upload,
 *   auto-switches to pdf mode with the returned path as source_ref
 *
 * Fields: paper_id, source_type, source_ref, paper_content.
 */

import { useEffect, useRef, useState } from 'react';
import { FileText, Link2, Send, FolderOpen, Upload, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '../ui/legacy-button';
import { listRawPapers, uploadPaperFile, type RawFile } from '../../lib/paper-api';

type SourceType = 'pdf' | 'url' | 'raw';

// ─── Types ──────────────────────────────────────────────────

interface PaperFormProps {
  onSubmit: (req: {
    paper_id: string;
    source_type: SourceType;
    source_ref: string;
    paper_content: string;
    symbol: string;
    start_date: string;
    end_date: string;
  }) => Promise<void>;
  className?: string;
}

// ─── Component ──────────────────────────────────────────────

export function PaperForm({ onSubmit, className }: PaperFormProps) {
  const [paperId, setPaperId] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('pdf');
  const [sourceRef, setSourceRef] = useState('');
  const [paperContent, setPaperContent] = useState('');
  const [symbol, setSymbol] = useState('000300.SH');
  const [startDate, setStartDate] = useState('2023-01-01');
  const [endDate, setEndDate] = useState('2025-12-31');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Raw files
  const [rawFiles, setRawFiles] = useState<RawFile[]>([]);
  const [rawDir, setRawDir] = useState<string | null>(null);
  const [rawLoading, setRawLoading] = useState(false);

  // Upload
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canSubmit = paperId.trim() && !submitting && !uploading;

  // Load raw/ file list on mount and when switching to raw mode
  useEffect(() => {
    if (sourceType !== 'raw') return;
    setRawLoading(true);
    listRawPapers()
      .then((d) => {
        setRawFiles(d.files || []);
        setRawDir(d.raw_dir);
        if (d.files && d.files.length > 0 && !sourceRef) {
          setSourceRef(d.files[0].path);
        }
      })
      .catch(() => {
        setRawFiles([]);
        setRawDir(null);
      })
      .finally(() => setRawLoading(false));
  }, [sourceType, sourceRef]);

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
        symbol: symbol.trim() || '000300.SH',
        start_date: startDate || '2023-01-01',
        end_date: endDate || '2025-12-31',
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!paperId.trim()) {
      setError('请先填写 Paper ID');
      e.target.value = '';
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const result = await uploadPaperFile(paperId.trim(), file);
      setSourceType('pdf');
      setSourceRef(result.path);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // ─── Render ────────────────────────────────────────────────

  return (
    <div className={cn('space-y-3', className)}>
      {/* Paper ID + Source Type toggle + Submit row */}
      <div className="grid grid-cols-12 gap-2">
        <input
          type="text"
          value={paperId}
          onChange={(e) => setPaperId(e.target.value)}
          placeholder="Paper ID (e.g. arxiv-2501.12345)"
          className="col-span-3 px-3 py-2 bg-muted border border-border rounded-lg
            text-sm text-foreground placeholder-muted-foreground
            focus:outline-none focus:border-primary font-mono"
          disabled={submitting || uploading}
        />

        <div className="col-span-3 flex gap-1">
          {(['pdf', 'url', 'raw'] as SourceType[]).map((t) => {
            const Icon = t === 'pdf' ? FileText : t === 'url' ? Link2 : FolderOpen;
            return (
              <button
                key={t}
                onClick={() => { setSourceType(t); setSourceRef(''); }}
                disabled={submitting || uploading}
                className={cn(
                  'flex-1 px-2 py-2 rounded-lg text-xs font-medium transition-colors',
                  sourceType === t
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:text-foreground',
                )}
                title={t === 'pdf' ? '本地 PDF' : t === 'url' ? 'URL' : 'raw/ 仓库'}
              >
                <Icon className="w-3 h-3 inline mr-1" />
                {t.toUpperCase()}
              </button>
            );
          })}
        </div>

        <Button
          onClick={handleSubmit}
          disabled={!canSubmit}
          variant="primary"
          size="sm"
          className="col-span-3"
        >
          {submitting ? (
            <span className="animate-pulse flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              提交中...
            </span>
          ) : (
            <>
              <Send className="w-3 h-3 inline mr-1" />
              开始提取
            </>
          )}
        </Button>

        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={!paperId.trim() || uploading || submitting}
          className="col-span-3 px-3 py-2 rounded-lg text-xs font-medium
            bg-muted text-foreground hover:bg-muted/70 transition-colors
            disabled:opacity-50 disabled:cursor-not-allowed
            flex items-center justify-center gap-1.5"
          title="上传本地 PDF"
        >
          {uploading ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin" />
              上传中...
            </>
          ) : (
            <>
              <Upload className="w-3 h-3" />
              上传 PDF
            </>
          )}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          onChange={handleFileSelected}
          className="hidden"
        />
      </div>

      {/* Source ref row — different UI per type */}
      {sourceType === 'raw' ? (
        <div className="bg-muted border border-border rounded-lg p-2">
          {rawLoading ? (
            <div className="text-xs text-muted-foreground px-2 py-1.5">加载 raw/ 文件列表...</div>
          ) : rawFiles.length === 0 ? (
            <div className="text-xs text-muted-foreground px-2 py-1.5">
              raw/ 目录为空
              {rawDir && <span className="font-mono ml-1 opacity-70">({rawDir})</span>}
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {rawFiles.map((f) => (
                <button
                  key={f.filename}
                  onClick={() => {
                    setSourceRef(f.path);
                    if (!paperId.trim()) {
                      setPaperId(f.filename.replace(/\.pdf$/i, ''));
                    }
                  }}
                  className={cn(
                    'px-2.5 py-1 rounded text-xs font-mono transition-colors',
                    sourceRef === f.path
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-background text-foreground hover:bg-primary/20',
                  )}
                  title={`${f.path} · ${(f.size_bytes / 1024).toFixed(1)} KB`}
                >
                  {f.filename}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <input
          type="text"
          value={sourceRef}
          onChange={(e) => setSourceRef(e.target.value)}
          placeholder={sourceType === 'pdf' ? '/path/to/paper.pdf' : 'https://arxiv.org/abs/...'}
          className="w-full px-3 py-2 bg-muted border border-border rounded-lg
            text-sm text-foreground placeholder-muted-foreground
            focus:outline-none focus:border-primary"
          disabled={submitting || uploading}
        />
      )}

      <textarea
        value={paperContent}
        onChange={(e) => setPaperContent(e.target.value)}
        placeholder="粘贴论文内容（可选，留空则从 source_ref 读取）..."
        className="w-full h-20 px-3 py-2 bg-muted border border-border rounded-lg
          text-sm text-foreground placeholder-muted-foreground
          focus:outline-none focus:border-primary resize-none font-mono"
        disabled={submitting || uploading}
      />

      {/* Auto-backtest params */}
      <div className="grid grid-cols-12 gap-2">
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="标的代码 (000300.SH)"
          className="col-span-4 px-3 py-1.5 bg-muted border border-border rounded-lg
            text-xs text-foreground placeholder-muted-foreground font-mono
            focus:outline-none focus:border-primary"
          disabled={submitting || uploading}
        />
        <input
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          className="col-span-3 px-3 py-1.5 bg-muted border border-border rounded-lg
            text-xs text-foreground font-mono
            focus:outline-none focus:border-primary"
          disabled={submitting || uploading}
        />
        <input
          type="date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          className="col-span-3 px-3 py-1.5 bg-muted border border-border rounded-lg
            text-xs text-foreground font-mono
            focus:outline-none focus:border-primary"
          disabled={submitting || uploading}
        />
        <div className="col-span-2 flex items-center justify-center text-[10px] text-muted-foreground">
          自动回测
        </div>
      </div>

      {error && (
        <div className="text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-lg p-2">
          {error}
        </div>
      )}
    </div>
  );
}
