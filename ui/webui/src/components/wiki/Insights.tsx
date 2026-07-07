import { useState, useEffect } from 'react';
import {
  Lightbulb, Sparkles, Network, RefreshCw, Loader2, FileText,
  Link2, AlertTriangle, BarChart3, CheckCircle2, ArrowRight,
  AlertCircle,
} from 'lucide-react';
import { api, GraphAnalysis } from '../../api';
import { GraphAnalysisPanel } from './GraphAnalysisPanel';
import { LoadingState, EmptyState } from '../ui/states';
import { cn } from '@/lib/utils';

interface SynthesisResult {
  source: string;
  status: string;
  reinforced_claims?: Array<{ claim: string; sources: string[]; confidence: number }>;
  contradictions?: Array<{ claim_a: string; claim_b: string; sources: string[] }>;
  knowledge_gaps?: Array<{ topic: string; description: string }>;
}

export function Insights() {
  const [recommendations, setRecommendations] = useState<Array<Record<string, unknown>>>([]);
  const [synthesisResults, setSynthesisResults] = useState<SynthesisResult[]>([]);
  const [graphAnalysis, setGraphAnalysis] = useState<GraphAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [synthesisLoading, setSynthesisLoading] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);

  useEffect(() => { loadInsights(); }, []);

  const loadInsights = async () => {
    setLoading(true);
    try {
      const recs = await api.wiki.recommend() as unknown as Record<string, unknown>;
      const flattened: Array<Record<string, unknown>> = [];
      if (recs && typeof recs === 'object') {
        const missingPages = (recs.missing_pages as Array<Record<string, unknown>>) || [];
        const orphanPages = (recs.orphan_pages as Array<Record<string, unknown>>) || [];
        missingPages.forEach((p) => flattened.push({ ...p, type: 'missing_page' }));
        orphanPages.forEach((p) => flattened.push({ ...p, type: 'orphan' }));
      }
      setRecommendations(flattened);
    } catch { setRecommendations([]); } finally { setLoading(false); }
  };

  const loadSynthesis = async () => {
    setSynthesisLoading(true);
    try {
      const result = await api.wiki.suggestSynthesis() as unknown as Record<string, unknown>;
      if (result && typeof result === 'object') {
        const suggestions = (result.suggestions as Array<Record<string, unknown>>) || [];
        setSynthesisResults(suggestions as unknown as SynthesisResult[]);
      }
    } catch { setSynthesisResults([]); } finally { setSynthesisLoading(false); }
  };

  const loadGraphAnalysis = async () => {
    setGraphLoading(true);
    try {
      const result = await api.wiki.graphAnalyze();
      setGraphAnalysis(result as unknown as GraphAnalysis);
    } catch { setGraphAnalysis(null); } finally { setGraphLoading(false); }
  };

  if (loading) return <LoadingState message="Loading insights…" />;

  return (
    <div className="overflow-y-auto h-full">
      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        {/* Header */}
        <div className="mb-2">
          <h1 className="text-2xl font-semibold text-foreground tracking-tight">Insights</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Recommendations, cross-source synthesis, and graph analysis
          </p>
        </div>

        {/* Recommendations */}
        <Section
          icon={Lightbulb}
          title="Recommendations"
          description="Missing and orphan pages that need attention"
          actionLabel="Refresh"
          onAction={loadInsights}
        >
          {recommendations.length === 0 ? (
            <EmptyState
              variant="compact"
              icon={<Lightbulb className="w-5 h-5" />}
              title="No recommendations"
              description="All pages look well-connected."
            />
          ) : (
            <div className="space-y-2">
              {recommendations.map((rec, i) => {
                const pageName = rec.page as string | undefined;
                const recType = rec.type as string | undefined;
                const isMissing = recType === 'missing_page';
                const isOrphan = recType === 'orphan';
                const message = pageName
                  ? `${isMissing ? 'Missing page' : isOrphan ? 'Orphan page' : 'Suggestion'}: ${pageName}`
                  : String(rec.message || rec.observation || recType || 'Recommendation');
                const Icon = isMissing ? FileText : isOrphan ? Link2 : Sparkles;
                const toneStyle = isMissing
                  ? 'border-warning/30 bg-warning/5'
                  : isOrphan
                  ? 'border-info/30 bg-info/5'
                  : 'border-primary/30 bg-primary/5';
                const iconColor = isMissing
                  ? 'text-warning bg-warning/15'
                  : isOrphan
                  ? 'text-foreground/70 bg-white/[0.04]'
                  : 'text-primary bg-primary/15';
                return (
                  <div
                    key={i}
                    className={cn(
                      'flex items-start gap-3 p-3 rounded-lg border transition-colors',
                      'hover:bg-white/[0.02]',
                      toneStyle,
                    )}
                  >
                    <div className={cn('w-7 h-7 rounded-md flex items-center justify-center shrink-0', iconColor)}>
                      <Icon className="w-3.5 h-3.5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-foreground">{message}</p>
                      {rec.suggestion !== undefined && rec.suggestion !== null && (
                        <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                          <ArrowRight className="w-3 h-3 shrink-0" />
                          <span>{String(rec.suggestion)}</span>
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Section>

        {/* Synthesis */}
        <Section
          icon={Sparkles}
          title="Cross-Source Synthesis"
          description="Detects reinforced claims, contradictions, and knowledge gaps"
          actionLabel={synthesisLoading ? 'Loading…' : 'Run Analysis'}
          onAction={loadSynthesis}
          loading={synthesisLoading}
        >
          {synthesisResults.length === 0 ? (
            <EmptyState
              variant="compact"
              icon={<Sparkles className="w-5 h-5" />}
              title="No synthesis results"
              description='Click "Run Analysis" to find reinforced claims, contradictions, and gaps across your sources.'
            />
          ) : (
            <div className="space-y-3">
              {synthesisResults.map((result, i) => (
                <div key={i} className="rounded-lg glass p-4 space-y-3">
                  <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <FileText className="w-3.5 h-3.5 text-primary" />
                    {result.source || 'Source Analysis'}
                  </h3>

                  {result.reinforced_claims && result.reinforced_claims.length > 0 && (
                    <InsightGroup
                      icon={CheckCircle2}
                      iconColor="text-success"
                      title="Reinforced Claims"
                      count={result.reinforced_claims.length}
                    >
                      {result.reinforced_claims.slice(0, 3).map((claim, j) => (
                        <div key={j} className="flex items-start gap-2 text-xs">
                          <span className="text-success shrink-0 mt-0.5">✓</span>
                          <div className="flex-1 min-w-0">
                            <p className="text-foreground/90">{claim.claim}</p>
                            <p className="text-[10px] text-muted-foreground mt-0.5">
                              {claim.sources.length} sources · confidence {(claim.confidence * 100).toFixed(0)}%
                            </p>
                          </div>
                        </div>
                      ))}
                    </InsightGroup>
                  )}

                  {result.contradictions && result.contradictions.length > 0 && (
                    <InsightGroup
                      icon={AlertTriangle}
                      iconColor="text-destructive"
                      title="Contradictions"
                      count={result.contradictions.length}
                    >
                      {result.contradictions.slice(0, 3).map((contra, j) => (
                        <div key={j} className="text-xs text-foreground/90 space-y-1">
                          <div className="flex items-start gap-1.5">
                            <span className="text-destructive shrink-0">A:</span>
                            <span className="italic">"{contra.claim_a}"</span>
                          </div>
                          <div className="flex items-start gap-1.5">
                            <span className="text-destructive shrink-0">B:</span>
                            <span className="italic">"{contra.claim_b}"</span>
                          </div>
                        </div>
                      ))}
                    </InsightGroup>
                  )}

                  {result.knowledge_gaps && result.knowledge_gaps.length > 0 && (
                    <InsightGroup
                      icon={AlertCircle}
                      iconColor="text-warning"
                      title="Knowledge Gaps"
                      count={result.knowledge_gaps.length}
                    >
                      {result.knowledge_gaps.slice(0, 3).map((gap, j) => (
                        <div key={j} className="text-xs">
                          <span className="text-warning font-medium">{gap.topic}</span>
                          <span className="text-muted-foreground"> — {gap.description}</span>
                        </div>
                      ))}
                    </InsightGroup>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Graph Analysis */}
        <GraphAnalysisPanel
          data={graphAnalysis}
          loading={graphLoading}
          onRun={loadGraphAnalysis}
          runLabel="Run Analysis"
        />
      </div>
    </div>
  );
}

function Section({
  icon: Icon, title, description, actionLabel, onAction, loading, children,
}: {
  icon: typeof Lightbulb;
  title: string;
  description: string;
  actionLabel: string;
  onAction: () => void;
  loading?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl glass p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Icon className="w-4 h-4 text-primary" />
            {title}
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
        </div>
        <button
          onClick={onAction}
          disabled={loading}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium',
            'glass hover:bg-white/[0.04] text-foreground/85',
            'transition-colors shrink-0',
            'disabled:opacity-50',
          )}
        >
          {loading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <BarChart3 className="w-3.5 h-3.5" />
          )}
          <span>{actionLabel}</span>
        </button>
      </div>
      {children}
    </section>
  );
}

function InsightGroup({
  icon: Icon, iconColor, title, count, children,
}: {
  icon: typeof CheckCircle2;
  iconColor: string;
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <h4 className={cn('text-[11px] font-semibold uppercase tracking-wider flex items-center gap-1.5', iconColor)}>
        <Icon className="w-3 h-3" />
        {title} <span className="text-muted-foreground/70">({count})</span>
      </h4>
      <div className="space-y-1 pl-4">{children}</div>
    </div>
  );
}
