import { useState, useEffect, useMemo, useCallback, type ReactNode } from 'react';
import { api, type ResearchSession } from '../../api';
import { renderInlineCitations, buildSourceMap, type ReportSource } from '../ui/CitationRef';
import { WikiViewer } from './WikiViewer';
import { SaveToWikiModal } from './SaveToWikiModal';
import katex from 'katex';
import 'katex/dist/katex.min.css';

interface Props {
  sessionId: string;
  onBack: () => void;
}

function parseReport(result: string | null) {
  if (!result) return null;
  try { return JSON.parse(result); } catch { return null; }
}

function renderMath(latex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(latex, { displayMode, throwOnError: false, trust: true });
  } catch {
    return `<code class="text-red-400">${latex}</code>`;
  }
}

const INLINE_MATH_RE = /\$([^\$]+?)\$/g;

function renderInlineMath(text: string, sourceMap: Map<string, ReportSource>, openWiki?: (pageName: string) => void): ReactNode {
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  INLINE_MATH_RE.lastIndex = 0;
  while ((match = INLINE_MATH_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      const before = text.slice(lastIndex, match.index);
      parts.push(<span key={`t-${lastIndex}`}>{renderInlineCitations(before, sourceMap, openWiki)}</span>);
    }
    const html = renderMath(match[1], false);
    parts.push(
      <span
        key={`m-${match.index}`}
        className="inline-block align-middle mx-0.5"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
    lastIndex = INLINE_MATH_RE.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(<span key={`t-${lastIndex}`}>{renderInlineCitations(text.slice(lastIndex), sourceMap, openWiki)}</span>);
  }

  return parts.length === 0 ? renderInlineCitations(text, sourceMap, openWiki) : <>{parts}</>;
}

type MdBlock =
  | { type: 'heading'; level: number; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'blockquote'; text: string }
  | { type: 'code'; lang: string; text: string }
  | { type: 'hr' }
  | { type: 'paragraph'; text: string }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'math'; text: string };

function parseMdBlocks(markdown: string): MdBlock[] {
  const lines = markdown.split('\n');
  const blocks: MdBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (/^```/.test(line)) {
      const lang = line.slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }
      i++;
      blocks.push({ type: 'code', lang, text: codeLines.join('\n') });
      continue;
    }

    if (/^\$\$/.test(line.trim())) {
      const mathLines: string[] = [];
      i++; // skip opening $$
      while (i < lines.length && !/^\$\$/.test(lines[i].trim())) {
        mathLines.push(lines[i]);
        i++;
      }
      i++; // skip closing $$
      blocks.push({ type: 'math', text: mathLines.join('\n') });
      continue;
    }

    if (/^#{1,6}\s/.test(line)) {
      const match = line.match(/^(#{1,6})\s+(.*)/);
      if (match) {
        blocks.push({ type: 'heading', level: match[1].length, text: match[2] });
      }
      i++;
      continue;
    }

    if (/^>\s/.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length && /^>\s/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ''));
        i++;
      }
      blocks.push({ type: 'blockquote', text: quoteLines.join('\n') });
      continue;
    }

    if (/^\|/.test(line)) {
      const tableLines: string[] = [];
      while (i < lines.length && /^\|/.test(lines[i])) {
        tableLines.push(lines[i]);
        i++;
      }
      if (tableLines.length >= 2) {
        const parseRow = (row: string) =>
          row.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
        const headers = parseRow(tableLines[0]);
        const rows = tableLines.slice(2).map(parseRow); // skip separator row
        blocks.push({ type: 'table', headers, rows });
      }
      continue;
    }

    if (/^[-*]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ''));
        i++;
      }
      blocks.push({ type: 'list', ordered: false, items });
      continue;
    }

    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ''));
        i++;
      }
      blocks.push({ type: 'list', ordered: true, items });
      continue;
    }

    if (/^---+$/.test(line.trim())) {
      blocks.push({ type: 'hr' });
      i++;
      continue;
    }

    if (line.trim() === '') {
      i++;
      continue;
    }

    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() !== '' && !/^#{1,6}\s/.test(lines[i]) && !/^```/.test(lines[i]) && !/^>\s/.test(lines[i]) && !/^[-*]\s/.test(lines[i]) && !/^\d+\.\s/.test(lines[i]) && !/^---+$/.test(lines[i].trim()) && !/^\|/.test(lines[i]) && !/^\$\$/.test(lines[i].trim())) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: 'paragraph', text: paraLines.join('\n') });
    }
  }

  return blocks;
}

function renderBlock(block: MdBlock, sourceMap: Map<string, ReportSource>, openWiki?: (pageName: string) => void): ReactNode {
  switch (block.type) {
    case 'heading': {
      const Tag = `h${block.level}` as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6';
      const sizeClass = block.level === 1 ? 'text-xl' : block.level === 2 ? 'text-lg' : 'text-base';
      return (
        <Tag key={block.text} className={`${sizeClass} font-bold mt-6 mb-2 text-foreground`}>
          {renderInlineCitations(block.text, sourceMap, openWiki)}
        </Tag>
      );
    }
    case 'list':
      return block.ordered ? (
        <ol key={block.items[0]} className="list-decimal pl-6 my-2 space-y-1">
          {block.items.map((item, i) => (
            <li key={i} className="text-sm text-foreground leading-relaxed">
              {renderInlineMath(item, sourceMap, openWiki)}
            </li>
          ))}
        </ol>
      ) : (
        <ul key={block.items[0]} className="list-disc pl-6 my-2 space-y-1">
          {block.items.map((item, i) => (
            <li key={i} className="text-sm text-foreground leading-relaxed">
              {renderInlineMath(item, sourceMap, openWiki)}
            </li>
          ))}
        </ul>
      );
    case 'blockquote':
      return (
        <blockquote key={block.text} className="border-l-4 border-primary/30 pl-4 my-3 text-sm text-muted-foreground italic">
          {renderInlineMath(block.text, sourceMap, openWiki)}
        </blockquote>
      );
    case 'code':
      return (
        <pre key={block.text} className="bg-muted p-3 rounded-lg overflow-x-auto my-3 text-[12px] text-foreground font-mono">
          <code>{block.text}</code>
        </pre>
      );
    case 'math':
      return (
        <div key={block.text} className="my-4 overflow-x-auto text-center"
          dangerouslySetInnerHTML={{ __html: renderMath(block.text, true) }}
        />
      );
    case 'table':
      return (
        <div key={block.headers.join('|')} className="my-4 overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-border">
                {block.headers.map((h, hi) => (
                  <th key={hi} className="px-3 py-2 text-left text-muted-foreground font-medium text-xs">
                    {renderInlineCitations(h, sourceMap, openWiki)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri} className="border-b border-border/50">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3 py-2 text-foreground">
                      {renderInlineCitations(cell, sourceMap, openWiki)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case 'hr':
      return <hr key="hr" className="border-border my-6" />;
    case 'paragraph':
      return (
        <p key={block.text} className="text-sm leading-relaxed my-2 text-foreground">
          {renderInlineMath(block.text, sourceMap, openWiki)}
        </p>
      );
  }
}

function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  const colorClass = color || 'text-foreground';
  return (
    <div className="flex flex-col items-center justify-center px-3 py-2 bg-muted rounded border border-border min-w-[4rem]">
      <span className={`text-lg font-bold leading-none ${colorClass}`}>{value}</span>
      <span className="text-[10px] text-muted-foreground opacity-60 mt-1 leading-tight">{label}</span>
    </div>
  );
}

function formatCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function ReportDetail({ sessionId, onBack }: Props) {
  const [session, setSession] = useState<ResearchSession | null>(null);
  const [reportData, setReportData] = useState<ReturnType<typeof parseReport>>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [wikiViewer, setWikiViewer] = useState<{ pageName: string; wikiId?: string } | null>(null);
  const [saveModalOpen, setSaveModalOpen] = useState(false);

  const openWiki = useCallback((pageName: string) => {
    setWikiViewer({ pageName, wikiId: session?.wiki_id || undefined });
  }, [session]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const sess = await api.research.get(sessionId);
        if (!cancelled) { setSession(sess); setReportData(parseReport(sess.result)); }
      } catch (e) { if (!cancelled) setError(String(e)); }
      finally { if (!cancelled) setLoading(false); }
    };
    load();
    return () => { cancelled = true; };
  }, [sessionId]);

  const sources: ReportSource[] = useMemo(() => {
    if (!reportData?.sources) return [];
    return reportData.sources.map((s: { id: string; title: string; url: string; source_type: string }) => ({
      id: s.id, title: s.title || '', url: s.url || '', source_type: s.source_type || 'web',
    }));
  }, [reportData]);

  const sourceMap = useMemo(() => buildSourceMap(sources), [sources]);
  const qualityScore = reportData?.quality_score ?? 0;
  const rounds = reportData?.rounds ?? 0;
  const charCount = reportData?.markdown?.length ?? 0;
  const synthesisSummary = reportData?.synthesis_summary ?? {};
  const contradictions = synthesisSummary.contradictions ?? 0;
  const knowledgeGaps = synthesisSummary.knowledge_gaps ?? 0;
  const reinforcedClaims = synthesisSummary.reinforced_claims ?? 0;
  const qualityColor = qualityScore >= 7 ? 'text-green-400' : qualityScore >= 5 ? 'text-yellow-400' : 'text-red-400';
  const query = session?.query || reportData?.query || '';

  const blocks = useMemo(() => {
    if (!reportData?.markdown) return [];
    return parseMdBlocks(reportData.markdown);
  }, [reportData]);

  if (loading) {
    return (
      <div className="h-full flex flex-col">
        <Header onBack={onBack} />
        <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">Loading report...</div>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="h-full flex flex-col">
        <Header onBack={onBack} />
        <div className="flex-1 flex items-center justify-center text-sm text-red-400">{error || 'Report not found'}</div>
      </div>
    );
  }

    return (
    <div className="h-full flex flex-col overflow-hidden">
      <Header
        onBack={onBack}
        query={query}
        qualityScore={qualityScore}
        onSaveToWiki={session?.wiki_page_name ? undefined : () => setSaveModalOpen(true)}
      />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          <div className="report-body relative">
            <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-gradient-to-b from-primary/40 via-primary/20 to-transparent pointer-events-none" />
            <div className="pl-4">
              <div className="flex flex-wrap gap-2 mb-6">
                <StatCard label="质量" value={`${qualityScore}/10`} color={qualityColor} />
                <StatCard label="轮次" value={rounds} />
                <StatCard label="来源" value={sources.length} />
                <StatCard label="字符" value={formatCount(charCount)} />
                {contradictions > 0 && <StatCard label="矛盾" value={contradictions} color="text-orange-400" />}
                {knowledgeGaps > 0 && <StatCard label="缺口" value={knowledgeGaps} color="text-yellow-400" />}
                {reinforcedClaims > 0 && <StatCard label="强化声明" value={reinforcedClaims} color="text-green-400" />}
              </div>

              {blocks.length > 0 ? (
                <div>{blocks.map((b, i) => renderBlock(b, sourceMap, openWiki))}</div>
              ) : (
                <div className="text-sm text-muted-foreground">No report content.</div>
              )}

              {sources.length > 0 && (
                <div className="mt-8 pt-4 border-t border-border">
                  <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide opacity-60">
                    References ({sources.length})
                  </div>
                  <div className="space-y-1.5">
                    {sources.map((src, i) => (
                      <div key={src.id} className="flex items-start gap-2 text-xs">
                        <span className="text-muted-foreground w-4 text-center shrink-0 mt-0.5">{i + 1}.</span>
                        {src.source_type === 'wiki' ? (
                          <button
                            onClick={() => openWiki(src.title || src.url.replace('wiki://', ''))}
                            className="text-primary hover:underline flex-1 truncate text-left"
                            title={src.url}
                          >
                            {src.title || src.url}
                          </button>
                        ) : (
                          <a href={src.url} target="_blank" rel="noopener noreferrer"
                            className="text-primary hover:underline flex-1 truncate" title={src.url}>
                            {src.title || src.url}
                          </a>
                        )}
                        <span className={`px-1 py-px rounded text-[9px] shrink-0 ${
                          src.source_type === 'arxiv' ? 'bg-purple-500/20 text-purple-400' :
                          src.source_type === 'pdf' ? 'bg-orange-500/20 text-orange-400' :
                          src.source_type === 'wiki' ? 'bg-purple-500/20 text-purple-400' :
                          src.source_type === 'youtube' ? 'bg-red-500/20 text-red-400' :
                          'bg-blue-500/20 text-primary'
                        }`}>
                          {src.source_type === 'arxiv' ? 'arXiv' : src.source_type === 'pdf' ? 'PDF' : src.source_type === 'wiki' ? 'Wiki' : src.source_type}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {wikiViewer && (
        <WikiViewer
          pageName={wikiViewer.pageName}
          wikiId={wikiViewer.wikiId}
          onClose={() => setWikiViewer(null)}
        />
      )}

      {saveModalOpen && (
        <SaveToWikiModal
          sessionId={sessionId}
          query={query}
          onClose={() => setSaveModalOpen(false)}
        />
      )}
    </div>
  );
}

function Header({ onBack, query, qualityScore, onSaveToWiki }: {
  onBack: () => void;
  query?: string;
  qualityScore?: number;
  onSaveToWiki?: () => void;
}) {
  return (
    <div className="px-4 py-3 border-b border-border flex items-center gap-3">
      <button onClick={onBack} className="text-muted-foreground hover:text-foreground shrink-0">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M11 2L5 8l6 6" />
        </svg>
      </button>
      <div className="flex-1 min-w-0">
        <h2 className="text-sm font-medium truncate">{query || 'Research Report'}</h2>
      </div>
      {qualityScore !== undefined && qualityScore > 0 && (
        <div className={`text-sm font-bold shrink-0 ${qualityScore >= 7 ? 'text-green-400' : qualityScore >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
          ★ {qualityScore}/10
        </div>
      )}
      {onSaveToWiki && (
        <button
          onClick={onSaveToWiki}
          className="text-xs px-2 py-1 rounded text-primary hover:bg-primary/10 shrink-0"
        >
          Save to Wiki
        </button>
      )}
    </div>
  );
}