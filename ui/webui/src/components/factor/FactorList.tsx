/**
 * FactorList — factor library 展示页.
 *
 * Fetches /api/factor/library/list, flattens the categories dict, and
 * renders selectable cards grouped by category. Clicking a card navigates
 * to the 6-layer detail page (/agent/factor/:name).
 */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Beaker, Loader2, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '../ui/legacy-badge';

interface FactorItem {
  _name?: string;
  _path?: string;
  name?: string;
  name_cn?: string;
  category?: string;
  subcategory?: string;
  factor_class?: string;
  status?: string;
  l1?: { definition?: string };
}

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  '已注册': 'secondary',
  '待验证': 'outline',
  '已通过': 'default',
  '失败': 'destructive',
};

export function FactorList() {
  const navigate = useNavigate();
  const [categories, setCategories] = useState<Record<string, FactorItem[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/factor/library/list')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (!cancelled) setCategories(data.categories || {});
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
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

  const catEntries = Object.entries(categories).filter(([, items]) => items.length > 0);
  const total = catEntries.reduce((n, [, items]) => n + items.length, 0);

  if (total === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 text-muted-foreground">
        <Beaker className="w-8 h-8 opacity-50" />
        <p className="text-sm">暂无因子</p>
        <p className="text-[11px] opacity-70">通过 Paper 抽取或在 quant/factors/ 手动创建</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center gap-2">
          <Beaker className="w-5 h-5 text-primary" />
          <h1 className="text-lg font-semibold">因子库</h1>
          <Badge variant="outline" className="ml-1">{total}</Badge>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          浏览因子定义 → 点击查看 6 层详情（逻辑 / 计算 / 金融 / 含义 / 验证 / 风险）
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6 space-y-6">
        {catEntries.map(([cat, items]) => (
          <section key={cat}>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              {cat} · {items.length}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {items.map((f) => {
                const slug = f._name ?? f._path ?? '';
                return (
                  <button
                    key={slug}
                    onClick={() => navigate(`/agent/factor/${encodeURIComponent(slug)}`)}
                    className="group text-left p-3 rounded-lg border border-border bg-card hover:border-primary/40 hover:bg-primary/[0.03] transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Beaker className="w-3.5 h-3.5 text-primary shrink-0" />
                        <span className="font-medium text-sm truncate">
                          {f.name_cn || f.name || slug}
                        </span>
                      </div>
                      <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-primary transition-colors" />
                    </div>
                    {f.l1?.definition && (
                      <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">
                        {f.l1.definition}
                      </p>
                    )}
                    <div className="flex items-center gap-1.5 mt-2">
                      {f.subcategory && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-muted text-muted-foreground font-mono">
                          {f.subcategory}
                        </span>
                      )}
                      {f.status && (
                        <Badge variant={STATUS_VARIANT[f.status] || 'outline'} className="text-[9px] px-1 py-0">
                          {f.status}
                        </Badge>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
