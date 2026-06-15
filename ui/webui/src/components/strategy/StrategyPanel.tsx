/**
 * StrategyPanel — strategy tracking main panel.
 *
 * Two states:
 *   1. Selection: StrategySelector + backtest config form
 *   2. Results: strategy definition + KPI + PnL + monthly heatmap
 *
 * Follows AutoResearchPanel pattern.
 */

import { useState, useEffect, useCallback } from 'react';
import { TrendingUp, Play, ArrowLeft, ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '../ui/legacy-button';
import { StrategySelector } from '../shared/StrategySelector';
import { MetricCards } from '../shared/MetricCards';
import { LineChart } from '../shared/LineChart';
import { HeatMap } from '../shared/HeatMap';
import { DrawdownChart } from '../shared/DrawdownChart';
import type { Metric } from '../shared/MetricCards';

// ─── Types ──────────────────────────────────────────────────

interface StrategyDef {
  strategy_class?: string;
  signal_type?: string;
  signal_params?: Record<string, unknown>;
  factor_refs?: string[];
  rebalance_freq?: string;
  status?: string;
  [key: string]: unknown;
}

interface StrategyMetrics {
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_return: number;
  cagr: number;
  sortino_ratio: number;
  alpha: number;
  beta: number;
}

interface BacktestResult {
  slug: string;
  strategy: StrategyDef;
  metrics: StrategyMetrics;
  equity_curve: Array<{ date: string; value: number }>;
  monthly_returns: Record<string, number>;
  trades_count: number;
  status: string;
  data_source: string;
}

// ─── Component ──────────────────────────────────────────────

export function StrategyPanel() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<StrategyDef | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [symbol, setSymbol] = useState('600660.SH');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-03-31');
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);

  // Fetch strategy definition when selected
  useEffect(() => {
    if (!selectedSlug) {
      setStrategy(null);
      setResult(null);
      return;
    }
    setFetching(true);
    fetch(`/api/strategy/${selectedSlug}`)
      .then((r) => r.json())
      .then((data) => {
        setStrategy(data.strategy);
        setResult(null);
      })
      .catch(() => setStrategy(null))
      .finally(() => setFetching(false));
  }, [selectedSlug]);

  const handleBacktest = useCallback(async () => {
    if (!selectedSlug) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/strategy/${selectedSlug}/backtest`, {
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

  // Empty state: no strategy selected
  if (!selectedSlug) {
    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="p-4 border-b border-border bg-card">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-semibold">策略跟踪</h2>
          </div>
          <p className="text-xs text-muted-foreground">
            选择策略 → 回测验证 → KPI + PnL + 月度收益
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <StrategySelector onSelect={setSelectedSlug} />
        </div>
      </div>
    );
  }

  // Strategy selected: show definition + backtest config + results
  const kpiMetrics: Metric[] = result ? [
    { label: 'Sharpe', value: result.metrics.sharpe_ratio.toFixed(3) },
    { label: 'Sortino', value: result.metrics.sortino_ratio.toFixed(3) },
    { label: '最大回撤', value: `${(result.metrics.max_drawdown * 100).toFixed(2)}%` },
    { label: '胜率', value: `${(result.metrics.win_rate * 100).toFixed(1)}%` },
    { label: 'CAGR', value: `${(result.metrics.cagr * 100).toFixed(2)}%` },
    { label: '交易数', value: String(result.trades_count) },
  ] : [];

  // Parse monthly returns for heatmap: {"YYYY-MM": value} → {year: {month: value}}
  const heatmapRows: string[] = [];
  const heatmapCols: string[] = [];
  const heatmapData: Record<string, Record<number, number>> = {};

  if (result?.monthly_returns) {
    const nested: Record<number, Record<number, number>> = {};
    for (const [ym, val] of Object.entries(result.monthly_returns)) {
      const parts = ym.split('-');
      if (parts.length === 2) {
        const y = parseInt(parts[0]);
        const m = parseInt(parts[1]);
        if (!isNaN(y) && !isNaN(m)) {
          if (!nested[y]) nested[y] = {};
          nested[y][m] = val;
        }
      }
    }
    const years = Object.keys(nested).sort();
    const months = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'];
    heatmapRows.push(...years);
    heatmapCols.push(...months);
    for (const year of years) {
      heatmapData[year] = nested[parseInt(year)] || {};
    }
  }

  // Compute drawdown series from equity curve
  const drawdownData = result?.equity_curve ? (() => {
    let peak = result.equity_curve[0]?.value ?? 0;
    return result.equity_curve.map((pt) => {
      if (pt.value > peak) peak = pt.value;
      return { date: new Date(pt.date), drawdown: peak > 0 ? (pt.value - peak) / peak : 0 };
    });
  })() : [];

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
          <TrendingUp className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold">{strategy?.signal_type || selectedSlug}</h2>
        </div>

        {/* Strategy definition */}
        {strategy && (
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground mb-2">
            <span>类型: {strategy.strategy_class}</span>
            <span>信号: {strategy.signal_type}</span>
            {strategy.signal_params && (
              <span className="font-mono">{JSON.stringify(strategy.signal_params)}</span>
            )}
            <span>换仓: {strategy.rebalance_freq}</span>
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
              <span className="animate-pulse">回测中...</span>
            ) : (
              <>
                <Play className="w-3 h-3 inline mr-1" />
                开始回测
              </>
            )}
          </Button>
        </div>

        {result && (
          <div className="text-[10px] text-muted-foreground mt-1">
            数据源: {result.data_source}
          </div>
        )}
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* KPI Cards */}
        {kpiMetrics.length > 0 && (
          <MetricCards metrics={kpiMetrics} columns={6} />
        )}

        {/* Equity Curve */}
        {result && result.equity_curve && result.equity_curve.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              净值曲线
            </h3>
            <div className="bg-card border border-border rounded-lg p-4">
              <LineChart
                series={[{
                  id: 'equity',
                  label: 'Equity',
                  data: result.equity_curve.map((pt) => ({ date: pt.date, value: pt.value })),
                }]}
                height={200}
                showArea
                yFormat={(n) => `${(n / 10000).toFixed(1)}万`}
              />
            </div>
          </section>
        )}

        {/* Drawdown Chart */}
        {result && drawdownData.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              回撤分析
            </h3>
            <div className="bg-card border border-border rounded-lg p-4">
              <DrawdownChart
                data={drawdownData}
                height={160}
                topN={3}
              />
            </div>
          </section>
        )}

        {/* Monthly Returns Heatmap */}
        {result && heatmapRows.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              月度收益
            </h3>
            <div className="bg-card border border-border rounded-lg p-4">
              <HeatMap
                rows={heatmapRows}
                cols={heatmapCols}
                data={heatmapData}
                format={(v) => `${v.toFixed(1)}%`}
                height={Math.max(120, heatmapRows.length * 32)}
              />
            </div>
          </section>
        )}

        {/* Strategy definition page */}
        {strategy && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              策略定义
            </h3>
            <div className="bg-card border border-border rounded-lg p-3 text-xs text-foreground space-y-1">
              {strategy.factor_refs && strategy.factor_refs.length > 0 && (
                <div>
                  <span className="text-muted-foreground">引用因子: </span>
                  {strategy.factor_refs.map((ref) => (
                    <span key={ref} className="font-mono text-primary">{ref} </span>
                  ))}
                </div>
              )}
              <div>
                <span className="text-muted-foreground">状态: </span>
                {strategy.status}
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}