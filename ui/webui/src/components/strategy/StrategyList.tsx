/**
 * StrategyList — strategy library 展示页.
 *
 * Fetches /api/strategy/list and renders selectable cards. Clicking a card
 * navigates to the strategy detail page (/agent/strategy/:name).
 */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { TrendingUp, Loader2, ChevronRight } from 'lucide-react';
import { Badge } from '../ui/legacy-badge';

interface StrategyItem {
  _slug?: string;
  _path?: string;
  name?: string;
  name_cn?: string;
  title?: string;
  strategy_class?: string;
  signal_type?: string;
  rebalance_freq?: string;
  status?: string;
}

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  '已注册': 'secondary',
  draft: 'outline',
  backtested: 'secondary',
  validated: 'default',
  deprecated: 'destructive',
};

export function StrategyList() {
  const navigate = useNavigate();
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/strategy/list')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (!cancelled) setStrategies(data.strategies || []);
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
        <TrendingUp className="w-8 h-8 opacity-50" />
        <p className="text-sm">{error}</p>
      </div>
    );
  }

  if (strategies.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 text-muted-foreground">
        <TrendingUp className="w-8 h-8 opacity-50" />
        <p className="text-sm">暂无策略</p>
        <p className="text-[11px] opacity-70">通过 Paper 抽取或在 quant/strategies/ 手动创建</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-primary" />
          <h1 className="text-lg font-semibold">策略库</h1>
          <Badge variant="outline" className="ml-1">{strategies.length}</Badge>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          浏览策略定义 → 点击查看详情（逻辑 / 计算 / 金融 / 含义）
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {strategies.map((s) => {
            const slug = s._slug ?? s._path ?? '';
            return (
              <button
                key={slug}
                onClick={() => navigate(`/agent/strategy/${encodeURIComponent(slug)}`)}
                className="group text-left p-3 rounded-lg border border-border bg-card hover:border-primary/40 hover:bg-primary/[0.03] transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <TrendingUp className="w-3.5 h-3.5 text-primary shrink-0" />
                    <span className="font-medium text-sm truncate">
                      {s.name_cn || s.title || s.name || slug}
                    </span>
                  </div>
                  <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0 group-hover:text-primary transition-colors" />
                </div>
                <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                  {s.strategy_class && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-muted text-muted-foreground font-mono">
                      {s.strategy_class}
                    </span>
                  )}
                  {s.signal_type && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-muted text-muted-foreground">
                      {s.signal_type}
                    </span>
                  )}
                  {s.status && (
                    <Badge variant={STATUS_VARIANT[s.status] || 'outline'} className="text-[9px] px-1 py-0">
                      {s.status}
                    </Badge>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
