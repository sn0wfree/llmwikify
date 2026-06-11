/**
 * FactorPanel — single-factor testing main panel.
 *
 * Two states:
 *   1. Selection: FactorSelector + backtest config form
 *   2. Results: factor definition + IC/quantile metrics + charts
 *
 * Supports cross-section (universe) mode and legacy single-stock mode.
 */

import { useState, useEffect, useCallback } from 'react';
import { Beaker, Play, ArrowLeft } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '../ui/Button';
import { FactorSelector } from '../shared/FactorSelector';
import { MetricCards } from '../shared/MetricCards';
import { ICChart } from '../shared/ICChart';
import { QuantileCurves } from '../shared/QuantileCurves';
import { LongShortCurveChart } from '../shared/LongShortCurveChart';
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
  rank_ic_mean?: number;
  rank_ic_std?: number;
  rank_icir?: number;
  longshort_ann_return?: number;
  longshort_sharpe?: number;
  longshort_mdd?: number;
}

interface BacktestResult {
  slug: string;
  factor: FactorDef;
  metrics: FactorMetrics;
  ic_series?: Array<{ date: string; ic: number }>;
  quantile_curves?: Record<string, Array<{ date: string; value: number }>>;
  longshort_curve?: Array<{ date: string; value: number }>;
  universe?: string;
  adj_mode?: string;
  n_stocks_per_date?: number[];
  status: string;
}

// ─── Component ──────────────────────────────────────────────

export function FactorPanel() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [factor, setFactor] = useState<FactorDef | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);

  // Config state
  const [universe, setUniverse] = useState('HS300');
  const [customUniverse, setCustomUniverse] = useState('');
  const [adjMode, setAdjMode] = useState('M-end');
  const [hedge, setHedge] = useState('equal');
  const [nGroups, setNGroups] = useState(5);
  const [factorDirection, setFactorDirection] = useState(1);
  const [symbol, setSymbol] = useState('600660.SH'); // legacy single mode
  const [startDate, setStartDate] = useState('2023-01-01');
  const [endDate, setEndDate] = useState('2024-12-31');
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

  const effectiveUniverse = universe === 'custom' ? customUniverse : universe;

  const handleBacktest = useCallback(async () => {
    if (!selectedSlug) return;
    setLoading(true);
    try {
      const body: Record<string, unknown> = {
        universe: effectiveUniverse,
        adj_mode: adjMode,
        hedge,
        n_groups: nGroups,
        factor_direction: factorDirection,
        start_date: startDate,
        end_date: endDate,
      };
      // Legacy single mode
      if (universe === 'single') {
        body.symbol = symbol;
        body.benchmark_code = symbol;
      }
      const res = await fetch(`/api/factor/${selectedSlug}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
    } finally {
      setLoading(false);
    }
  }, [selectedSlug, effectiveUniverse, adjMode, hedge, nGroups, factorDirection, startDate, endDate, symbol, universe]);

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
            选择因子 → 股票池截面 IC/IR → 分层回测 → 多空组合
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
    { label: 'Rank IC', value: (result.metrics.rank_ic_mean ?? 0).toFixed(4) },
    { label: 'IC IR', value: result.metrics.icir.toFixed(4) },
    { label: 'Rank ICIR', value: (result.metrics.rank_icir ?? 0).toFixed(4) },
    { label: '胜率', value: `${(result.metrics.win_rate * 100).toFixed(1)}%` },
    { label: '多头年化', value: `${(result.metrics.annual_return * 100).toFixed(1)}%` },
    { label: '多空年化', value: `${((result.metrics.longshort_ann_return ?? 0) * 100).toFixed(1)}%` },
    { label: '多空 Sharpe', value: (result.metrics.longshort_sharpe ?? 0).toFixed(2) },
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

        {/* Backtest config form */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Universe selector */}
          <select
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            className="px-2 py-1 bg-muted border border-border rounded text-xs
              text-foreground focus:outline-none focus:border-primary"
          >
            <option value="HS300">沪深 300</option>
            <option value="ZZ500">中证 500</option>
            <option value="SZ50">上证 50</option>
            <option value="ZZ1000">中证 1000</option>
            <option value="all">全 A 股</option>
            <option value="single">单标的 (旧)</option>
            <option value="custom">自定义...</option>
          </select>

          {universe === 'custom' && (
            <input
              type="text"
              value={customUniverse}
              onChange={(e) => setCustomUniverse(e.target.value)}
              className="w-28 px-2 py-1 bg-muted border border-border rounded text-xs font-mono
                text-foreground focus:outline-none focus:border-primary"
              placeholder="指数代码"
            />
          )}
          {universe === 'single' && (
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="w-28 px-2 py-1 bg-muted border border-border rounded text-xs font-mono
                text-foreground focus:outline-none focus:border-primary"
              placeholder="Symbol"
            />
          )}

          {/* Adj mode */}
          <select
            value={adjMode}
            onChange={(e) => setAdjMode(e.target.value)}
            className="px-2 py-1 bg-muted border border-border rounded text-xs
              text-foreground focus:outline-none focus:border-primary"
          >
            <option value="D">日频</option>
            <option value="M-end">月频 (月末)</option>
            <option value="W-end">周频 (周五)</option>
          </select>

          {/* Hedge */}
          <select
            value={hedge}
            onChange={(e) => setHedge(e.target.value)}
            className="px-2 py-1 bg-muted border border-border rounded text-xs
              text-foreground focus:outline-none focus:border-primary"
          >
            <option value="equal">等权</option>
            <option value="HS300">HS300 对冲</option>
            <option value="ZZ500">ZZ500 对冲</option>
            <option value="SZ50">SZ50 对冲</option>
          </select>

          {/* n_groups */}
          <select
            value={nGroups}
            onChange={(e) => setNGroups(Number(e.target.value))}
            className="px-2 py-1 bg-muted border border-border rounded text-xs
              text-foreground focus:outline-none focus:border-primary"
          >
            {[3, 5, 10].map((n) => (
              <option key={n} value={n}>{n} 组</option>
            ))}
          </select>

          {/* Factor direction */}
          <select
            value={factorDirection}
            onChange={(e) => setFactorDirection(Number(e.target.value))}
            className="px-2 py-1 bg-muted border border-border rounded text-xs
              text-foreground focus:outline-none focus:border-primary"
          >
            <option value={1}>越大越好 ↑</option>
            <option value={-1}>越小越好 ↓</option>
          </select>

          {/* Dates */}
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
            disabled={loading || (!effectiveUniverse && universe !== 'single')}
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

        {/* Info bar */}
        {result && result.universe !== 'single' && result.n_stocks_per_date && result.n_stocks_per_date.length > 0 && (
          <div className="mt-2 text-[10px] text-muted-foreground font-mono">
            股票池: {result.universe} · 调仓频率: {result.adj_mode} ·
            截面平均: {Math.round(result.n_stocks_per_date.reduce((a, b) => a + b, 0) / result.n_stocks_per_date.length)} 只/期
            · 调仓次数: {result.n_stocks_per_date.length}
          </div>
        )}
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {metrics.length > 0 && (
          <MetricCards metrics={metrics} columns={4} />
        )}

        {/* IC Time Series + Distribution */}
        {result && result.ic_series && result.ic_series.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              IC 分析
            </h3>
            <div className="bg-card border border-border rounded-lg p-4">
              <ICChart
                icSeries={result.ic_series.map((pt: { date: string; ic: number }) => ({
                  date: pt.date,
                  ic: pt.ic,
                }))}
                height={300}
              />
            </div>
          </section>
        )}

        {/* Quantile Curves */}
        {result && result.quantile_curves && Object.keys(result.quantile_curves).length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              分层净值曲线
            </h3>
            <div className="bg-card border border-border rounded-lg p-4">
              <QuantileCurves
                groups={result.quantile_curves}
                height={280}
              />
            </div>
          </section>
        )}

        {/* Long-Short Curve */}
        {result && result.longshort_curve && result.longshort_curve.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              多空组合净值
            </h3>
            <div className="bg-card border border-border rounded-lg p-4">
              <LongShortCurveChart
                curve={result.longshort_curve}
                height={200}
              />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
