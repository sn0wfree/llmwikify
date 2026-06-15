/**
 * NewSessionForm — input form for creating a new reproduction session.
 *
 * Fields:
 *   - Paper ID
 *   - Source type (pdf / url)
 *   - Source ref (path or URL)
 *   - Symbol (e.g. 600660.SH)
 *   - Date range
 */

import { useState } from 'react';
import { Calendar, FileText, Link2, TrendingUp } from 'lucide-react';
import { Card } from '../ui/legacy-card';
import { Button } from '../ui/legacy-button';
import { startReproduction } from '../../lib/reproduction-api';

interface NewSessionFormProps {
  onCreated: (sessionId: string) => void;
}

const TODAY = new Date().toISOString().slice(0, 10);
const THREE_MONTHS_AGO = new Date(Date.now() - 90 * 86400_000).toISOString().slice(0, 10);

export function NewSessionForm({ onCreated }: NewSessionFormProps) {
  const [paperId, setPaperId] = useState('');
  const [sourceType, setSourceType] = useState<'pdf' | 'url'>('pdf');
  const [sourceRef, setSourceRef] = useState('');
  const [symbol, setSymbol] = useState('600660.SH');
  const [startDate, setStartDate] = useState(THREE_MONTHS_AGO);
  const [endDate, setEndDate] = useState(TODAY);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = paperId.trim() && sourceRef.trim() && symbol.trim()
    && startDate && endDate && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await startReproduction({
        paper_id: paperId.trim(),
        source_type: sourceType,
        source_ref: sourceRef.trim(),
        symbol: symbol.trim(),
        start_date: startDate,
        end_date: endDate,
      });
      onCreated(result.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-background min-h-0">
      <div className="min-h-full flex flex-col items-center justify-center p-8">
        <div className="w-full max-w-2xl py-4">
          <div className="text-center mb-6">
            <h2 className="text-2xl font-bold text-primary mb-2">
              论文策略复现
            </h2>
            <p className="text-sm text-muted-foreground">
              Wiki TradingStrategy → 数据回测 → 指标分析 → Wiki 归档
            </p>
          </div>

          <Card padding="md">
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-2">
                  <FileText className="w-3 h-3 inline mr-1" />
                  论文 ID
                </label>
                <input
                  type="text"
                  value={paperId}
                  onChange={(e) => setPaperId(e.target.value)}
                  placeholder="例如：arxiv-2501.12345"
                  className="w-full px-3 py-2 bg-muted border border-border rounded
                    text-sm text-foreground placeholder-muted-foreground
                    focus:outline-none focus:border-primary"
                  disabled={submitting}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-2">
                    来源类型
                  </label>
                  <div className="flex gap-1">
                    <button
                      onClick={() => setSourceType('pdf')}
                      disabled={submitting}
                      className={`flex-1 px-3 py-2 rounded text-xs font-medium transition-colors ${
                        sourceType === 'pdf'
                          ? 'bg-primary text-white'
                          : 'bg-muted text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      PDF
                    </button>
                    <button
                      onClick={() => setSourceType('url')}
                      disabled={submitting}
                      className={`flex-1 px-3 py-2 rounded text-xs font-medium transition-colors ${
                        sourceType === 'url'
                          ? 'bg-primary text-white'
                          : 'bg-muted text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      URL
                    </button>
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-2">
                    <Link2 className="w-3 h-3 inline mr-1" />
                    来源路径
                  </label>
                  <input
                    type="text"
                    value={sourceRef}
                    onChange={(e) => setSourceRef(e.target.value)}
                    placeholder={sourceType === 'pdf' ? '/path/to/paper.pdf' : 'https://...'}
                    className="w-full px-3 py-2 bg-muted border border-border rounded
                      text-sm text-foreground placeholder-muted-foreground
                      focus:outline-none focus:border-primary"
                    disabled={submitting}
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-2">
                  <TrendingUp className="w-3 h-3 inline mr-1" />
                  股票代码 (symbol)
                </label>
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  placeholder="例如：600660.SH"
                  className="w-full px-3 py-2 bg-muted border border-border rounded
                    text-sm text-foreground placeholder-muted-foreground
                    focus:outline-none focus:border-primary font-mono"
                  disabled={submitting}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-2">
                    <Calendar className="w-3 h-3 inline mr-1" />
                    开始日期
                  </label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-2 bg-muted border border-border rounded
                      text-sm text-foreground
                      focus:outline-none focus:border-primary"
                    disabled={submitting}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-2">
                    <Calendar className="w-3 h-3 inline mr-1" />
                    结束日期
                  </label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-2 bg-muted border border-border rounded
                      text-sm text-foreground
                      focus:outline-none focus:border-primary"
                    disabled={submitting}
                  />
                </div>
              </div>

              {error && (
                <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded p-2">
                  {error}
                </div>
              )}

              <Button
                onClick={handleSubmit}
                disabled={!canSubmit}
                variant="primary"
                size="md"
                className="w-full"
              >
                {submitting ? '运行 5 阶段流水线...' : '开始复现'}
              </Button>
            </div>
          </Card>

          <div className="mt-6 grid grid-cols-5 gap-2 text-[10px]">
            {[1, 2, 3, 4, 5].map((n) => (
              <div
                key={n}
                className="bg-card border border-border rounded p-2 text-center"
              >
                <div className="font-bold text-primary mb-0.5">{n}</div>
                <div className="text-muted-foreground">
                  {['提取', '数据', '回测', 'Wiki', '完成'][n - 1]}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}