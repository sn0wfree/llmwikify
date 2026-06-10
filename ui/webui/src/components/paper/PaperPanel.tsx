/**
 * PaperPanel — paper reproduction main panel.
 *
 * Two states:
 *   1. Empty: PaperForm for starting extraction
 *   2. Results: extraction results + artifacts (Factor/Strategy pages)
 *
 * Follows AutoResearchPanel pattern: sidebar-less, full-width layout.
 */

import { useState, useEffect, useCallback } from 'react';
import { ArrowLeft, FileText, Beaker, TrendingUp, ExternalLink, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PaperForm } from './PaperForm';

// ─── Types ──────────────────────────────────────────────────

interface PaperResult {
  paper_id: string;
  extraction: Record<string, unknown>;
  pages_written: string[];
  status: string;
}

interface Artifact {
  kind: string;
  wiki_page: string;
  page_type: string;
}

// ─── Component ──────────────────────────────────────────────

export function PaperPanel() {
  const [result, setResult] = useState<PaperResult | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (req: {
    paper_id: string;
    source_type: 'pdf' | 'url';
    source_ref: string;
    paper_content: string;
  }) => {
    setLoading(true);
    try {
      const res = await fetch('/api/paper/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);

      // Fetch artifacts
      const artRes = await fetch(`/api/paper/${req.paper_id}/artifacts`);
      if (artRes.ok) {
        const artData = await artRes.json();
        setArtifacts(artData.artifacts || []);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setArtifacts([]);
  };

  // Empty state
  if (!result) {
    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="p-4 border-b border-border bg-card">
          <div className="flex items-center gap-2 mb-1">
            <FileText className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-semibold">论文理解</h2>
          </div>
          <p className="text-xs text-muted-foreground">
            从论文/研报中结构化抽取策略逻辑、因子定义、风险分析
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <PaperForm onSubmit={handleSubmit} />
          {loading && (
            <div className="mt-4 text-center text-sm text-muted-foreground animate-pulse">
              正在提取论文结构...
            </div>
          )}
        </div>
      </div>
    );
  }

  // Results state
  const extraction = result.extraction || {};
  const logic = extraction.strategy_logic as Record<string, string> | undefined;
  const data = extraction.data_requirements as Record<string, unknown> | undefined;
  const risks = extraction.risks as Record<string, string[]> | undefined;
  const suggested = extraction.suggested_signal as Record<string, unknown> | undefined;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="p-4 border-b border-border bg-card">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <FileText className="w-4 h-4 text-primary" />
              <h2 className="text-sm font-semibold">论文理解</h2>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-success/20 text-success">
                ✓ 已完成
              </span>
            </div>
            <div className="text-xs text-muted-foreground font-mono">
              {result.paper_id} · {result.pages_written.length} pages written
            </div>
          </div>
          <button
            onClick={handleReset}
            className="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded
              border border-border"
          >
            <RefreshCw className="w-3 h-3 inline mr-1" />
            新建
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Strategy Logic */}
        {logic && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              策略逻辑
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(logic).map(([key, value]) => (
                <div key={key} className="bg-card border border-border rounded-lg p-3">
                  <div className="text-[10px] text-muted-foreground mb-1">{key}</div>
                  <div className="text-xs text-foreground">{value}</div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Data Requirements */}
        {data && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              数据需求
            </h3>
            <div className="bg-card border border-border rounded-lg p-3">
              {Object.entries(data).map(([key, value]) => (
                <div key={key} className="flex items-center gap-2 text-xs py-1">
                  <span className="text-muted-foreground">{key}:</span>
                  <span className="text-foreground">
                    {Array.isArray(value) ? value.join(', ') : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Risks */}
        {risks && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              风险与偏差
            </h3>
            <div className="bg-card border border-border rounded-lg p-3 space-y-1">
              {Object.entries(risks).map(([key, items]) => (
                <div key={key}>
                  <div className="text-[10px] text-muted-foreground mb-1">{key}</div>
                  {items.map((item, i) => (
                    <div key={i} className="text-xs text-foreground pl-2">- {item}</div>
                  ))}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Suggested Signal */}
        {suggested && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              建议信号
            </h3>
            <div className="bg-card border border-border rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-primary/10 text-primary">
                  {String(suggested.signal_type)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  confidence: {String(suggested.confidence)}
                </span>
              </div>
              <div className="text-xs text-foreground">{String(suggested.reasoning)}</div>
            </div>
          </section>
        )}

        {/* Artifacts */}
        {artifacts.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              产出 ({artifacts.length})
            </h3>
            <div className="space-y-2">
              {artifacts.map((a) => {
                const Icon = a.kind === 'Factor' ? Beaker
                  : a.kind === 'Strategy' ? TrendingUp
                  : FileText;
                return (
                  <div
                    key={a.wiki_page}
                    className="bg-card border border-border rounded-lg p-3
                      hover:border-primary/40 transition-colors group"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center">
                          <Icon className="w-3.5 h-3.5 text-primary" />
                        </div>
                        <div>
                          <div className="text-sm font-medium text-foreground">{a.kind}</div>
                          <div className="text-[10px] text-muted-foreground font-mono">
                            {a.wiki_page}
                          </div>
                        </div>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-muted-foreground
                        group-hover:text-primary transition-colors" />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}