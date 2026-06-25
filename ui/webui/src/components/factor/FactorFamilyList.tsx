/**
 * FactorFamilyList — L0 库首页: 族卡区 + 散因子区
 *
 * Fetches /api/factor/families, renders family cards and standalone factors.
 */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Beaker, Loader2, ChevronRight, BookOpen, Layers } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '../ui/legacy-badge';

interface Family {
  slug: string;
  display_name: string;
  description: string;
  type: 'collection' | 'composite';
  member_count: number;
  status_counts: Record<string, number>;
  ic_coverage: string;
}

interface Standalone {
  slug: string;
  name: string;
}

interface FamiliesResponse {
  families: Family[];
  standalone: Standalone[];
}

const STATUS_COLORS: Record<string, string> = {
  '已验证': 'bg-emerald-500',
  '已注册': 'bg-slate-400',
  '草稿': 'bg-slate-300',
  '已废弃': 'bg-rose-500',
};

export function FactorFamilyList() {
  const navigate = useNavigate();
  const [data, setData] = useState<FamiliesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/factor/families')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 text-muted-foreground">
        <Beaker className="w-8 h-8 opacity-50" />
        <p className="text-sm">{error}</p>
      </div>
    );
  }

  const families = data?.families || [];
  const standalone = data?.standalone || [];
  const totalMembers = families.reduce((n, f) => n + f.member_count, 0);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center gap-2">
          <Beaker className="w-5 h-5 text-primary" />
          <h1 className="text-lg font-semibold">因子库</h1>
          <Badge variant="outline" className="ml-1">
            {families.length} 族 · {totalMembers} 成员
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          因子族 → 成员表 → 6 层详情
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* Family cards */}
        {families.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              因子族 · {families.length}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {families.map((fam) => (
                <button
                  key={fam.slug}
                  onClick={() => navigate(`/agent/factor/fam/${fam.slug}`)}
                  className="group text-left p-4 rounded-lg border border-border bg-card hover:border-primary/40 hover:bg-primary/[0.03] transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Layers className="w-4 h-4 text-primary shrink-0" />
                      <span className="font-medium text-sm truncate">{fam.display_name}</span>
                    </div>
                    <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-primary transition-colors" />
                  </div>

                  {fam.description && (
                    <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
                      {fam.description}
                    </p>
                  )}

                  {/* Status bar */}
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden flex">
                      {Object.entries(fam.status_counts || {}).map(([status, count]) => (
                        <div
                          key={status}
                          className={cn('h-full', STATUS_COLORS[status] || 'bg-slate-300')}
                          style={{ width: `${(count / fam.member_count) * 100}%` }}
                        />
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>{fam.member_count} 成员</span>
                    <span>IC 覆盖 {fam.ic_coverage}</span>
                  </div>

                  <div className="flex items-center gap-1 mt-2">
                    <Badge variant="outline" className="text-[9px] px-1 py-0">
                      {fam.type === 'composite' ? 'composite' : 'alpha 族'}
                    </Badge>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {/* Standalone factors */}
        {standalone.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              独立因子 · {standalone.length}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {standalone.map((sf) => (
                <button
                  key={sf.slug}
                  onClick={() => navigate(`/agent/factor/${encodeURIComponent(sf.slug)}`)}
                  className="group text-left p-3 rounded-lg border border-border bg-card hover:border-primary/40 hover:bg-primary/[0.03] transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <BookOpen className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                      <span className="text-sm truncate">{sf.name}</span>
                    </div>
                    <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-primary transition-colors" />
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {/* Empty state */}
        {families.length === 0 && standalone.length === 0 && (
          <div className="flex flex-col items-center justify-center h-64 gap-2 text-muted-foreground">
            <Beaker className="w-8 h-8 opacity-50" />
            <p className="text-sm">暂无因子</p>
            <p className="text-[11px] opacity-70">通过 Paper 抽取或在 quant/factors/ 手动创建</p>
          </div>
        )}
      </div>
    </div>
  );
}
