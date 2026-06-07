import { useState, useEffect } from 'react';
import { api } from '../api';

interface SynthesisResult {
  source: string;
  status: string;
  reinforced_claims?: Array<{ claim: string; sources: string[]; confidence: number }>;
  contradictions?: Array<{ claim_a: string; claim_b: string; sources: string[] }>;
  knowledge_gaps?: Array<{ topic: string; description: string }>;
}

interface GraphAnalysis {
  status: string;
  centrality?: {
    pagerank: Array<{ node: string; score: number }>;
    hubs: Array<{ node: string; out_degree: number }>;
    authorities: Array<{ node: string; in_degree: number }>;
  };
  communities?: {
    num_communities: number;
    modularity: number;
    communities: Record<string, { label: string; size: number; members: string[] }>;
    bridges: Array<{ node: string; communities_connected: number }>;
  };
  suggestions?: Array<{ type: string; node: string; priority: string; observation: string; suggestion: string }>;
  stats?: { nodes: number; edges: number; density: number; avg_degree: number; is_connected: boolean };
}

export function Insights() {
  const [recommendations, setRecommendations] = useState<Array<Record<string, unknown>>>([]);
  const [synthesisResults, setSynthesisResults] = useState<SynthesisResult[]>([]);
  const [graphAnalysis, setGraphAnalysis] = useState<GraphAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [synthesisLoading, setSynthesisLoading] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);

  useEffect(() => {
    loadInsights();
  }, []);

  const loadInsights = async () => {
    setLoading(true);
    try {
      const recs = await api.wiki.recommend() as unknown as Record<string, unknown>;
      // API returns {missing_pages: [...], orphan_pages: [...], summary: '...'}
      // Flatten into a single array for display
      const flattened: Array<Record<string, unknown>> = [];
      if (recs && typeof recs === 'object') {
        const missingPages = (recs.missing_pages as Array<Record<string, unknown>>) || [];
        const orphanPages = (recs.orphan_pages as Array<Record<string, unknown>>) || [];
        missingPages.forEach(p => {
          flattened.push({ ...p, type: 'missing_page' });
        });
        orphanPages.forEach(p => {
          flattened.push({ ...p, type: 'orphan' });
        });
      }
      setRecommendations(flattened);
    } catch {
      setRecommendations([]);
    } finally {
      setLoading(false);
    }
  };

  const loadSynthesis = async () => {
    setSynthesisLoading(true);
    try {
      const result = await api.wiki.suggestSynthesis() as unknown as Record<string, unknown>;
      // API returns {suggestions: [...], sources_analyzed: N, ...}
      if (result && typeof result === 'object') {
        const suggestions = (result.suggestions as Array<Record<string, unknown>>) || [];
        setSynthesisResults(suggestions as unknown as SynthesisResult[]);
      }
    } catch {
      setSynthesisResults([]);
    } finally {
      setSynthesisLoading(false);
    }
  };

  const loadGraphAnalysis = async () => {
    setGraphLoading(true);
    try {
      const result = await api.wiki.graphAnalyze();
      setGraphAnalysis(result as unknown as GraphAnalysis);
    } catch {
      setGraphAnalysis(null);
    } finally {
      setGraphLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Loading insights...
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto overflow-y-auto h-full">
      <h2 className="text-xl font-bold mb-6">Insights</h2>

      <div className="space-y-6">
        {/* Recommendations */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-blue-400">Recommendations</h3>
            <button
              onClick={loadInsights}
              className="px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded"
            >
              Refresh
            </button>
          </div>
          {recommendations.length === 0 ? (
            <p className="text-slate-500 text-sm">No recommendations at this time.</p>
          ) : (
            <div className="space-y-2">
              {recommendations.map((rec, i) => {
                const pageName = rec.page as string | undefined;
                const recType = rec.type as string | undefined;
                const icon = recType === 'missing_page' ? '📄' : recType === 'orphan' ? '🔗' : '💡';
                const message = pageName
                  ? `${recType === 'missing_page' ? 'Missing page' : 'Orphan page'}: ${pageName}`
                  : String(rec.message || rec.observation || recType || 'Recommendation');

                return (
                  <div key={i} className="p-3 bg-slate-800 rounded border border-slate-700">
                    <div className="flex items-start gap-2">
                      <span className="text-blue-400 mt-0.5">{icon}</span>
                      <div>
                        <p className="text-sm">{message}</p>
                        {typeof rec.suggestion !== 'undefined' && rec.suggestion !== null && (
                          <p className="text-xs text-slate-400 mt-1">→ {String(rec.suggestion)}</p>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Synthesis */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-purple-400">Synthesis</h3>
            <button
              onClick={loadSynthesis}
              disabled={synthesisLoading}
              className="px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded"
            >
              {synthesisLoading ? 'Loading...' : 'Analyze'}
            </button>
          </div>
          {synthesisResults.length === 0 ? (
            <p className="text-slate-500 text-sm">
              Click "Analyze" to run cross-source synthesis. Detects contradictions, gaps, and reinforced claims.
            </p>
          ) : (
            <div className="space-y-3">
              {synthesisResults.map((result, i) => (
                <div key={i} className="bg-slate-800 rounded border border-slate-700 p-4">
                  <h4 className="text-sm font-medium text-slate-300 mb-2">{result.source || 'Source Analysis'}</h4>
                  {result.reinforced_claims && result.reinforced_claims.length > 0 && (
                    <div className="mb-3">
                      <p className="text-xs text-green-400 font-medium mb-1">Reinforced Claims ({result.reinforced_claims.length})</p>
                      {result.reinforced_claims.slice(0, 3).map((claim, j) => (
                        <div key={j} className="text-xs text-slate-400 ml-2 mb-1">
                          • {claim.claim} <span className="text-slate-500">(confidence: {(claim.confidence * 100).toFixed(0)}%)</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {result.contradictions && result.contradictions.length > 0 && (
                    <div className="mb-3">
                      <p className="text-xs text-red-400 font-medium mb-1">Contradictions ({result.contradictions.length})</p>
                      {result.contradictions.slice(0, 3).map((contra, j) => (
                        <div key={j} className="text-xs text-slate-400 ml-2 mb-1">
                          • "{contra.claim_a}" vs "{contra.claim_b}"
                        </div>
                      ))}
                    </div>
                  )}
                  {result.knowledge_gaps && result.knowledge_gaps.length > 0 && (
                    <div>
                      <p className="text-xs text-amber-400 font-medium mb-1">Knowledge Gaps ({result.knowledge_gaps.length})</p>
                      {result.knowledge_gaps.slice(0, 3).map((gap, j) => (
                        <div key={j} className="text-xs text-slate-400 ml-2 mb-1">
                          • {gap.topic}: {gap.description}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Graph Analysis */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-green-400">Graph Analysis</h3>
            <button
              onClick={loadGraphAnalysis}
              disabled={graphLoading}
              className="px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded"
            >
              {graphLoading ? 'Loading...' : 'Analyze'}
            </button>
          </div>
          {!graphAnalysis ? (
            <p className="text-slate-500 text-sm">
              Click "Analyze" to run knowledge graph analysis. Reveals central topics, community structures, and page suggestions.
            </p>
          ) : (
            <div className="space-y-4">
              {/* Stats */}
              {graphAnalysis.stats && (
                <div className="grid grid-cols-5 gap-3">
                  <StatCard label="Nodes" value={graphAnalysis.stats.nodes} />
                  <StatCard label="Edges" value={graphAnalysis.stats.edges} />
                  <StatCard label="Density" value={graphAnalysis.stats.density.toFixed(3)} />
                  <StatCard label="Avg Degree" value={graphAnalysis.stats.avg_degree.toFixed(1)} />
                  <StatCard label="Connected" value={graphAnalysis.stats.is_connected ? 'Yes' : 'No'} />
                </div>
              )}

              {/* PageRank Hubs */}
              {graphAnalysis.centrality?.pagerank && graphAnalysis.centrality.pagerank.length > 0 && (
                <div className="bg-slate-800 rounded border border-slate-700 p-4">
                  <h4 className="text-sm font-medium text-blue-400 mb-2">Top Pages (PageRank)</h4>
                  <div className="space-y-1">
                    {graphAnalysis.centrality.pagerank.slice(0, 5).map((item, i) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <span className="text-slate-300">{i + 1}. {item.node}</span>
                        <span className="text-slate-500">{item.score.toFixed(4)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Communities */}
              {graphAnalysis.communities && (
                <div className="bg-slate-800 rounded border border-slate-700 p-4">
                  <h4 className="text-sm font-medium text-purple-400 mb-2">
                    Communities ({graphAnalysis.communities.num_communities})
                  </h4>
                  <p className="text-xs text-slate-500 mb-2">
                    Modularity: {graphAnalysis.communities.modularity.toFixed(3)}
                  </p>
                  <div className="space-y-2">
                    {Object.entries(graphAnalysis.communities.communities).slice(0, 5).map(([cid, comm]) => (
                      <div key={cid} className="text-xs text-slate-400">
                        <span className="text-slate-300">{comm.label}</span>
                        <span className="text-slate-500 ml-2">{comm.size} nodes</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Suggestions */}
              {graphAnalysis.suggestions && graphAnalysis.suggestions.length > 0 && (
                <div className="bg-slate-800 rounded border border-slate-700 p-4">
                  <h4 className="text-sm font-medium text-amber-400 mb-2">
                    Suggested Pages ({graphAnalysis.suggestions.length})
                  </h4>
                  <div className="space-y-2">
                    {graphAnalysis.suggestions.slice(0, 5).map((sugg, i) => (
                      <div key={i} className="text-xs">
                        <span className={`px-1.5 py-0.5 rounded mr-2 ${
                          sugg.priority === 'high' ? 'bg-red-500/20 text-red-400' :
                          sugg.priority === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                          'bg-green-500/20 text-green-400'
                        }`}>
                          {sugg.priority}
                        </span>
                        <span className="text-slate-300">{sugg.observation}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-slate-800 rounded border border-slate-700 p-3 text-center">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="text-lg font-bold text-slate-200">{value}</div>
    </div>
  );
}
