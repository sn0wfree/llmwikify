/**
 * FactorPanel — single-factor testing main panel.
 *
 * Two states:
 *   1. Selection: FactorSelector + backtest config form
 *   2. Results: factor definition + IC/quantile metrics + charts
 *
 * Follows AutoResearchPanel pattern.
 */

import { useState, useEffect, useCallback } from 'react';
import { Beaker, Play, ArrowLeft } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '../ui/Button';
import { FactorSelector } from '../shared/FactorSelector';
import { MetricCards } from '../shared/MetricCards';
import { LineChart } from '../shared/LineChart';
import type { Metric } from '../shared/MetricCards';

// ─── Types ──────────────────────────────────────────────────

interface FactorDef {
  factor_class?: string;
  factor_params?: Record<string, unknown>;
  factor_source?: string;
  status?: string;
  [key: string]: unknown;
}

interface FactorMetrics {
  ic_mean: number;
  ic_std: number;
  icir: number;
  t_stat: number;
  win_rate: number;
  annual_return: number;
  max_drawdown: number;
  turnover: number;
}

interface BacktestResult {
  slug: string;
  factor: FactorDef;
  metrics: FactorMetrics;
  status: string;
}

// ─── Component ──────────────────────────────────────────────

export function FactorPanel() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [factor, setFactor] = useState<FactorDef | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [symbol, setSymbol] = useState('600660.SH');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-03-31');
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);

  // Fetch factor definition when selected
  useEffect(() => {
    if (!selectedSlug) {
      setFactor(null);
      setResult(null);
      return;
    }
    setFetching(true);
    fetch(`/api/factor/${selectedSlug}`)
      .then((r) => r.json())
      .then((data) => {
        setFactor(data.factor);
        setResult(null);
      })
      .catch(() => setFactor(null))
      .finally(() => setFetching(false));
  }, [selectedSlug]);

  const handleBacktest = useCallback(async () => {
    if (!selectedSlug) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/factor/${selectedSlug}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, start_date: startDate, end_date: endDate }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
    } finally {
      setLoading(false);
    }
  }, [selectedSlug, symbol, startDate, endDate]);

  // Empty state: no factor selected
  if (!selectedSlug) {
    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="p-4 border-b border-border bg-card">
          <div className="flex items-center gap-2 mb-1">
            <Beaker className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-semibold">单因子测试</h2>
          </div>
          <p className="text-xs text-muted-foreground">
            选择因子 → IC/IR 分析 → 分层回测
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <FactorSelector onSelect={setSelectedSlug} />
        </div>
      </div>
    );
  }

  // Factor selected: show definition + backtest config + results
  const metrics: Metric[] = result ? [
    { label: 'IC 均值', value: result.metrics.ic_mean.toFixed(4) },
    { label: 'IC IR', value: result.metrics.icir.toFixed(4) },
    { label: 'T 统计量', value: result.metrics.t_stat.toFixed(2) },
    { label: '胜率', value: `${(result.metrics.win_rate * 100).toFixed(1)}%` },
    { label: '年化收益', value: `${(result.metrics.annual_return * 100).toFixed(2)}%` },
    { label: '最大回撤', value: `${(result.metrics.max_drawdown * 100).toFixed(2)}%` },
  ] : [];

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="p-4 border-b border-border bg-card">
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={() => setSelectedSlug(null)}
            className="text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <Beaker className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold">{factor?.factor_class || selectedSlug}</h2>
        </div>

        {/* Factor definition */}
        {factor && (
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground mb-2">
            <span>类型: {factor.factor_class}</span>
            {factor.factor_params && (
              <span className="font-mono">{JSON.stringify(factor.factor_params)}</span>
            )}
            <span>来源: {factor.factor_source || 'N/A'}</span>
          </div>
        )}

        {/* Backtest config */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="w-28 px-2 py-1 bg-muted border border-border rounded text-xs font-mono
              text-foreground focus:outline-none focus:border-primary"
            placeholder="Symbol"
          />
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="px-2 py-1 bg-muted border border-border rounded text-xs
              text-foreground focus:outline-none focus:border-primary"
          />
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="px-2 py-1 bg-muted border border-border rounded text-xs
              text-foreground focus:outline-none focus:border-primary"
          />
          <Button
            onClick={handleBacktest}
            disabled={loading}
            variant="primary"
            size="sm"
          >
            {loading ? (
              <span className="animate-pulse">测试中...</span>
            ) : (
              <>
                <Play className="w-3 h-3 inline mr-1" />
                开始测试
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {result && result.status === 'stub' && (
          <div className="text-xs text-warning bg-warning/10 border border-warning/30 rounded-lg p-2">
            因子回测引擎尚未实现 (Phase 2.4)，当前返回占位数据
          </div>
        )}

        {metrics.length > 0 && (
          <MetricCards metrics={metrics} columns={6} />
        )}

        {/* IC Time Series placeholder */}
        {result && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              IC 时间序列
            </h3>
            <div className="bg-card border border-border rounded-lg p-4 h-48 flex items-center justify-center text-xs text-muted-foreground">
              IC chart — Phase 5 待实现
            </div>
          </section>
        )}

        {/* Quantile Curves placeholder */}
        {result && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              分层净值曲线
            </h3>
            <div className="bg-card border border-border rounded-lg p-4 h-48 flex items-center justify-center text-xs text-muted-foreground">
              Quantile curves — Phase 5 待实现
            </div>
          </section>
        )}
      </div>
    </div>
  );
}