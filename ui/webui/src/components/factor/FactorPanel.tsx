/**
 * FactorPanel — single-factor testing main panel (v3).
 *
 * Layout:
 *   Left sidebar: FactorSelector (factor list)
 *   Right: Header (glass + gradient) → InfoBar (always-on run summary) →
 *          4-tab results
 *
 * Tabs:
 *   1. 概览: 12 metric cards (4 groups × icon/color/bg) + group return bar
 *   2. IC 分析: IC time series + monthly heatmap
 *   3. 分层回测: quantile curves + group metrics table + group returns bar
 *   4. 多空组合: long-short NAV + drawdown
 *
 * Config: ConfigDrawer (right-side Radix Dialog) opened from InfoBar.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Beaker, Play, BarChart3, TrendingUp, Activity, Layers,
  Settings2, Info, Loader2, AlertTriangle, Target, Zap,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '../ui/legacy-button';
import { Badge } from '../ui/legacy-badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../ui/tooltip';
import { FactorSelector } from '../shared/FactorSelector';
import { MetricCards } from '../shared/MetricCards';
import { ICChart } from '../shared/ICChart';
import { QuantileCurves } from '../shared/QuantileCurves';
import { LongShortCurveChart } from '../shared/LongShortCurveChart';
import { GroupReturnBar } from '../shared/GroupReturnBar';
import { ICHeatMap } from '../shared/ICHeatMap';
import { DrawdownChart } from '../shared/DrawdownChart';
import { GroupMetricsTable } from './GroupMetricsTable';
import { ConfigDrawer, type ConfigState } from './ConfigDrawer';
import { posNegColor } from '@/lib/posNegColor';
import type { Metric } from '../shared/MetricCards';

// ─── Types ──────────────────────────────────────────────────

interface FactorDef {
  factor_class?: string;
  factor_params?: Record<string, unknown>;
  factor_source?: string;
  status?: string;
  description?: string;
  [key: string]: unknown;
}

interface GroupMetric {
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  turnover: number;
  n_stocks: number;
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
  rank_ic_pos_ratio?: number;
  longshort_ann_return?: number;
  longshort_sharpe?: number;
  longshort_mdd?: number;
  longshort_win_rate?: number;
}

interface BacktestResult {
  slug: string;
  factor: FactorDef;
  metrics: FactorMetrics & { group_metrics?: Record<string, GroupMetric> };
  ic_series?: Array<{ date: string; ic: number; rank_ic?: number; n_stocks?: number }>;
  quantile_returns?: Record<string, number>;
  quantile_curves?: Record<string, Array<{ date: string; value: number }>>;
  longshort_curve?: Array<{ date: string; value: number }>;
  universe?: string;
  adj_mode?: string;
  n_stocks_per_date?: Array<{ date: string; n: number }>;
  total_rebalances?: number;
  valid_rebalances?: number;
  status: string;
  run_id?: string;
}

type TabId = 'overview' | 'ic' | 'quantile' | 'longshort';

const TABS: { id: TabId; label: string; icon: typeof BarChart3 }[] = [
  { id: 'overview', label: '概览', icon: BarChart3 },
  { id: 'ic', label: 'IC 分析', icon: Activity },
  { id: 'quantile', label: '分层回测', icon: Layers },
  { id: 'longshort', label: '多空组合', icon: TrendingUp },
];

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  draft: 'outline',
  validated: 'default',
  deprecated: 'destructive',
};

const DEFAULT_CONFIG: ConfigState = {
  universe: 'HS300',
  customUniverse: '',
  adjMode: 'M-end',
  hedge: 'equal',
  nGroups: 5,
  factorDirection: 1,
  startDate: '2024-01-01',
  endDate: '2024-06-30',
  symbol: '600660.SH',
};

// ─── Component ──────────────────────────────────────────────

export function FactorPanel() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [factor, setFactor] = useState<FactorDef | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [config, setConfig] = useState<ConfigState>(DEFAULT_CONFIG);
  const [elapsedSec, setElapsedSec] = useState<number | null>(null);
  const startedAt = useRef<number | null>(null);

  // Fetch factor definition when selected
  useEffect(() => {
    if (!selectedSlug) {
      setFactor(null);
      setResult(null);
      setError(null);
      setElapsedSec(null);
      setActiveTab('overview');
      return;
    }
    setFetching(true);
    setError(null);
    fetch(`/api/factor/${selectedSlug}`)
      .then((r) => r.json())
      .then((data) => setFactor(data.factor))
      .catch(() => setFactor(null))
      .finally(() => setFetching(false));
  }, [selectedSlug]);

  const effectiveUniverse = config.universe === 'custom' ? config.customUniverse : config.universe;

  const handleBacktest = useCallback(async () => {
    if (!selectedSlug) return;
    setLoading(true);
    setError(null);
    startedAt.current = performance.now();
    try {
      const body: Record<string, unknown> = {
        universe: effectiveUniverse,
        adj_mode: config.adjMode,
        hedge: config.hedge,
        n_groups: config.nGroups,
        factor_direction: config.factorDirection,
        start_date: config.startDate,
        end_date: config.endDate,
      };
      if (config.universe === 'single') {
        body.symbol = config.symbol;
        body.benchmark_code = config.symbol;
      }
      const res = await fetch(`/api/factor/${selectedSlug}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setResult(data);
      setActiveTab('overview');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '回测失败');
    } finally {
      if (startedAt.current) {
        setElapsedSec((performance.now() - startedAt.current) / 1000);
      }
      setLoading(false);
    }
  }, [selectedSlug, effectiveUniverse, config]);

  // ─── Metric cards (4 groups × icon/color/bg) ───────────────

  const metrics: Metric[] = result ? [
    // 预测能力 (蓝)
    { label: 'IC 均值', value: result.metrics.ic_mean.toFixed(4), icon: Activity, color: 'text-blue-500', bg: 'bg-blue-500/10' },
    { label: 'Rank IC', value: (result.metrics.rank_ic_mean ?? 0).toFixed(4), icon: Activity, color: 'text-blue-500', bg: 'bg-blue-500/10' },
    { label: 'IC IR', value: result.metrics.icir.toFixed(4), icon: Target, color: 'text-blue-500', bg: 'bg-blue-500/10' },
    { label: 'Rank ICIR', value: (result.metrics.rank_icir ?? 0).toFixed(4), icon: Target, color: 'text-blue-500', bg: 'bg-blue-500/10' },
    { label: '胜率', value: `${(result.metrics.win_rate * 100).toFixed(1)}%`, icon: Target, color: 'text-blue-500', bg: 'bg-blue-500/10' },
    // 收益 (绿)
    { label: '多头年化', value: `${(result.metrics.annual_return * 100).toFixed(1)}%`, icon: TrendingUp, color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
    { label: '换手率', value: `${(result.metrics.turnover * 100).toFixed(1)}%`, icon: Zap, color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
    // 风险 (灰)
    { label: '最大回撤', value: `${(result.metrics.max_drawdown * 100).toFixed(1)}%`, icon: AlertTriangle, color: 'text-slate-500', bg: 'bg-slate-500/10' },
    // 多空对冲 (橙)
    { label: '多空年化', value: `${((result.metrics.longshort_ann_return ?? 0) * 100).toFixed(1)}%`, icon: TrendingUp, color: 'text-amber-500', bg: 'bg-amber-500/10' },
    { label: '多空 Sharpe', value: (result.metrics.longshort_sharpe ?? 0).toFixed(2), icon: BarChart3, color: 'text-amber-500', bg: 'bg-amber-500/10' },
    { label: '多空 MDD', value: `${((result.metrics.longshort_mdd ?? 0) * 100).toFixed(1)}%`, icon: AlertTriangle, color: 'text-amber-500', bg: 'bg-amber-500/10' },
    { label: '多空胜率', value: `${((result.metrics.longshort_win_rate ?? 0) * 100).toFixed(1)}%`, icon: Target, color: 'text-amber-500', bg: 'bg-amber-500/10' },
  ] : [];

  // ─── Drawdown data from longshort curve ─────────────────────

  const drawdownData = result?.longshort_curve
    ? computeDrawdown(result.longshort_curve)
    : [];

  // ─── Sidebar empty state ────────────────────────────────────

  if (!selectedSlug) {
    return (
      <div className="flex h-full min-h-0">
        <FactorSidebar />
        <div className="flex-1 flex items-center justify-center bg-gradient-to-br from-background to-muted/30">
          <EmptyState onOpenConfig={() => setConfigOpen(true)} />
        </div>
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-full min-h-0">
        <FactorSidebar selectedSlug={selectedSlug} onSelect={setSelectedSlug} />

        <div className="flex-1 flex flex-col min-h-0 min-w-0">
          {/* Header (glass + gradient) */}
          <div className="px-4 py-2.5 border-b border-border glass-strong bg-gradient-to-r from-primary/5 to-accent/5 flex items-center gap-3">
            <Beaker className="w-4 h-4 text-primary shrink-0" />
            <h2 className="text-sm font-semibold truncate">
              {String(factor?.title || factor?.factor_class || selectedSlug)}
            </h2>
            {factor && (
              <>
                <Badge variant="outline" className="shrink-0">{factor.factor_class}</Badge>
                {factor.factor_source && (
                  <span className="text-[10px] text-muted-foreground shrink-0 hidden sm:inline">
                    来自 {String(factor.factor_source).split('/').pop()}
                  </span>
                )}
                {factor.status && (
                  <Badge variant={STATUS_VARIANT[factor.status] || 'outline'} className="shrink-0">
                    {factor.status}
                  </Badge>
                )}
                {factor.description && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs">
                      <p className="text-xs">{String(factor.description)}</p>
                    </TooltipContent>
                  </Tooltip>
                )}
              </>
            )}
            <div className="flex-1" />
            <Button
              onClick={handleBacktest}
              disabled={loading}
              variant="primary"
              size="sm"
              className="shadow-soft"
            >
              {loading ? (
                <span className="animate-pulse">测试中...</span>
              ) : (
                <>
                  <Play className="w-3 h-3 mr-1" />
                  开始测试
                </>
              )}
            </Button>
          </div>

          {/* InfoBar (always-on run summary) */}
          <InfoBar
            config={config}
            result={result}
            effectiveUniverse={effectiveUniverse}
            elapsedSec={elapsedSec}
            onEdit={() => setConfigOpen(true)}
          />

          {/* Loading */}
          {loading && <LoadingState />}

          {/* Error */}
          {error && !loading && (
            <ErrorState error={error} onRetry={handleBacktest} onEdit={() => setConfigOpen(true)} />
          )}

          {/* Results */}
          {!loading && !error && result && (
            <>
              <div className="flex border-b border-border bg-card px-4">
                {TABS.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    onClick={() => setActiveTab(id)}
                    className={cn(
                      'flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px',
                      activeTab === id
                        ? 'border-primary text-foreground'
                        : 'border-transparent text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {label}
                  </button>
                ))}
              </div>

              <div key={activeTab} className="flex-1 overflow-y-auto p-4 animate-fade-in">
                {activeTab === 'overview' && (
                  <div className="space-y-4">
                    <MetricCards metrics={metrics} columns={4} />
                    {result.quantile_returns && Object.keys(result.quantile_returns).length > 0 && (
                      <Section title="分层年化收益">
                        <GroupReturnBar groups={result.quantile_returns} height={180} />
                      </Section>
                    )}
                  </div>
                )}

                {activeTab === 'ic' && (
                  <div className="space-y-4">
                    {result.ic_series && result.ic_series.length > 0 && (
                      <>
                        <Section title="IC 时序 + 分布">
                          <ICChart
                            icSeries={result.ic_series.map((pt) => ({
                              date: pt.date,
                              ic: pt.ic,
                            }))}
                            height={300}
                          />
                        </Section>
                        <Section title="IC 月度热力图">
                          <ICHeatMap icSeries={result.ic_series} height={120} />
                        </Section>
                      </>
                    )}
                  </div>
                )}

                {activeTab === 'quantile' && (
                  <div className="space-y-4">
                    {result.quantile_curves && Object.keys(result.quantile_curves).length > 0 && (
                      <Section title="分层净值曲线">
                        <QuantileCurves groups={result.quantile_curves} height={300} />
                      </Section>
                    )}
                    {result.metrics.group_metrics && Object.keys(result.metrics.group_metrics).length > 0 && (
                      <Section title="分组指标明细">
                        <GroupMetricsTable
                          groupMetrics={result.metrics.group_metrics}
                          groupReturns={result.quantile_returns || {}}
                          direction={(config.factorDirection as 1 | -1)}
                          longshort={{
                            ann_return: result.metrics.longshort_ann_return ?? 0,
                            sharpe: result.metrics.longshort_sharpe ?? 0,
                            mdd: result.metrics.longshort_mdd ?? 0,
                            win_rate: result.metrics.longshort_win_rate ?? 0,
                            turnover: result.metrics.turnover ?? 0,
                          }}
                        />
                      </Section>
                    )}
                    {result.quantile_returns && Object.keys(result.quantile_returns).length > 0 && (
                      <Section title="各组年化收益">
                        <GroupReturnBar groups={result.quantile_returns} height={180} />
                      </Section>
                    )}
                  </div>
                )}

                {activeTab === 'longshort' && (
                  <div className="space-y-4">
                    {result.longshort_curve && result.longshort_curve.length > 0 && (
                      <>
                        <Section title="多空净值">
                          <LongShortCurveChart curve={result.longshort_curve} height={240} />
                        </Section>
                        {drawdownData.length > 0 && (
                          <Section title="回撤">
                            <DrawdownChart data={drawdownData} height={180} topN={3} />
                          </Section>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            </>
          )}

          {/* Empty: selected but no result yet */}
          {!loading && !error && !result && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <div className="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-br from-primary/20 to-accent/20 flex items-center justify-center mb-3">
                  <Play className="w-6 h-6 text-primary" />
                </div>
                <h3 className="text-sm font-semibold mb-1">配置参数后点击「开始测试」</h3>
                <p className="text-xs text-muted-foreground">
                  或先
                  <button
                    onClick={() => setConfigOpen(true)}
                    className="text-primary hover:underline mx-1"
                  >
                    调整参数
                  </button>
                </p>
              </div>
            </div>
          )}
        </div>

        <ConfigDrawer
          open={configOpen}
          onOpenChange={setConfigOpen}
          value={config}
          onChange={setConfig}
          onApply={handleBacktest}
          loading={loading}
        />
      </div>
    </TooltipProvider>
  );
}

// ─── Sub-components ─────────────────────────────────────────

function FactorSidebar({ selectedSlug, onSelect }: { selectedSlug?: string; onSelect?: (s: string) => void }) {
  return (
    <div className="w-56 shrink-0 border-r border-border bg-card flex flex-col min-h-0">
      <div className="p-3 border-b border-border">
        <div className="flex items-center gap-2 mb-1">
          <Beaker className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold">单因子测试</h2>
        </div>
        <p className="text-[10px] text-muted-foreground">
          选择因子 → 截面 IC → 分层回测
        </p>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {onSelect ? (
          <FactorSelector onSelect={onSelect} selectedSlug={selectedSlug} />
        ) : (
          <FactorSelector onSelect={(_s: string) => {}} />
        )}
      </div>
    </div>
  );
}

function InfoBar({
  config,
  result,
  effectiveUniverse,
  elapsedSec,
  onEdit,
}: {
  config: ConfigState;
  result: BacktestResult | null;
  effectiveUniverse: string;
  elapsedSec: number | null;
  onEdit: () => void;
}) {
  return (
    <div className="px-4 py-2 border-b border-border bg-card/50 text-[10px] flex items-center gap-2 flex-wrap">
      <span className="font-medium text-muted-foreground">股票池</span>
      <span>{effectiveUniverse || '—'}</span>
      <Sep />
      <span className="font-medium text-muted-foreground">调仓</span>
      <span>{config.adjMode}</span>
      <Sep />
      <span className="font-medium text-muted-foreground">对冲</span>
      <span>{config.hedge}</span>
      <Sep />
      <span className="font-medium text-muted-foreground">分组</span>
      <span>{config.nGroups} 组</span>
      <Sep />
      <span className="font-medium text-muted-foreground">方向</span>
      <span>{config.factorDirection === 1 ? '↑' : '↓'}</span>
      <Sep />
      <span className="font-medium text-muted-foreground">区间</span>
      <span>{config.startDate} ~ {config.endDate}</span>

      {result && result.n_stocks_per_date && result.n_stocks_per_date.length > 0 && (
        <>
          <Sep />
          <span className="font-medium text-muted-foreground">截面平均</span>
          <span>{Math.round(result.n_stocks_per_date.reduce((a, b) => a + b.n, 0) / result.n_stocks_per_date.length)} 只/期</span>
          <Sep />
          <span className="font-medium text-muted-foreground">调仓</span>
          <span>{result.n_stocks_per_date.length} 次</span>
        </>
      )}

      {elapsedSec !== null && (
        <>
          <Sep />
          <span className="font-medium text-muted-foreground">耗时</span>
          <span>{elapsedSec.toFixed(1)}s</span>
        </>
      )}

      <div className="flex-1" />
      <button
        onClick={onEdit}
        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <Settings2 className="w-3 h-3" />
        修改
      </button>
    </div>
  );
}

function Sep() {
  return <span className="text-muted-foreground/40">·</span>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
        {title}
      </h3>
      <div className="bg-card border border-border rounded-lg p-4 glass-strong shadow-soft">
        {children}
      </div>
    </section>
  );
}

function LoadingState() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center">
        <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-br from-primary/20 to-accent/20 flex items-center justify-center mb-3 animate-pulse">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
        <div className="text-sm text-muted-foreground">回测计算中...</div>
      </div>
    </div>
  );
}

function ErrorState({ error, onRetry, onEdit }: { error: string; onRetry: () => void; onEdit: () => void }) {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center max-w-sm">
        <div className="w-14 h-14 mx-auto rounded-2xl bg-rose-500/10 flex items-center justify-center mb-3">
          <AlertTriangle className="w-6 h-6 text-rose-500" />
        </div>
        <h3 className="text-sm font-semibold text-destructive mb-1">回测失败</h3>
        <p className="text-xs text-muted-foreground mb-4">{error}</p>
        <div className="flex items-center justify-center gap-2">
          <Button onClick={onRetry} variant="secondary" size="sm">重试</Button>
          <Button onClick={onEdit} variant="secondary" size="sm">修改参数</Button>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onOpenConfig }: { onOpenConfig: () => void }) {
  return (
    <div className="text-center max-w-sm px-4">
      <div className="relative w-20 h-20 mx-auto mb-4">
        <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-primary/20 to-accent/20 blur-md" />
        <div className="relative w-full h-full rounded-3xl bg-gradient-to-br from-primary/20 to-accent/20 border border-primary/20 flex items-center justify-center">
          <Beaker className="w-8 h-8 text-primary" />
        </div>
      </div>
      <h3 className="text-sm font-semibold mb-2">开始单因子回测</h3>
      <div className="text-xs text-muted-foreground space-y-1.5 mb-4">
        <div>1. 左侧选择因子</div>
        <div>2. 点击右上「开始测试」</div>
        <div>3. 在下方查看 4 类分析结果</div>
      </div>
      <Button variant="secondary" size="sm" onClick={onOpenConfig}>
        <Settings2 className="w-3 h-3 mr-1" />
        先调整参数
      </Button>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────

function computeDrawdown(
  curve: Array<{ date: string; value: number }>,
): Array<{ date: string; drawdown: number }> {
  if (curve.length === 0) return [];
  let peak = curve[0].value;
  return curve.map((pt) => {
    if (pt.value > peak) peak = pt.value;
    return { date: pt.date, drawdown: pt.value / peak - 1 };
  });
}

// Re-export helper to suppress unused warning (imported for use in GroupMetricsTable)
export { posNegColor };
