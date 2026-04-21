import { useState, useEffect } from 'react';
import { api } from '../api';

export function Insights() {
  const [recommendations, setRecommendations] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadInsights();
  }, []);

  const loadInsights = async () => {
    setLoading(true);
    try {
      const recs = await api.wiki.recommend();
      setRecommendations(recs);
    } catch {
      setRecommendations([]);
    } finally {
      setLoading(false);
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
    <div className="p-6 max-w-4xl mx-auto">
      <h2 className="text-xl font-bold mb-4">Insights</h2>

      <div className="space-y-4">
        <section>
          <h3 className="text-lg font-semibold mb-2 text-blue-400">Recommendations</h3>
          {recommendations.length === 0 ? (
            <p className="text-slate-500 text-sm">No recommendations at this time.</p>
          ) : (
            recommendations.map((rec, i) => (
              <div key={i} className="p-3 bg-slate-800 rounded border border-slate-700 mb-2">
                <p className="text-sm">{String(rec.message || rec.type || 'Recommendation')}</p>
              </div>
            ))
          )}
        </section>

        <section>
          <h3 className="text-lg font-semibold mb-2 text-purple-400">Synthesis</h3>
          <p className="text-sm text-slate-400">
            Cross-source synthesis detects contradictions, gaps, and reinforced claims.
          </p>
        </section>

        <section>
          <h3 className="text-lg font-semibold mb-2 text-green-400">Graph Analysis</h3>
          <p className="text-sm text-slate-400">
            Knowledge graph analysis reveals central topics and community structures.
          </p>
        </section>
      </div>
    </div>
  );
}
